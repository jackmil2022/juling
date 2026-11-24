import type { ImagePrompt, VideoPrompt } from "@/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * 构图字段只为读取旧剧本保留。
 */
export function isStructuredImagePrompt(value: unknown): value is ImagePrompt {
  return isRecord(value) && typeof value.scene === "string";
}

/**
 * dialogue 可省略；若提供必须是 {speaker, line} 数组。
 */
export function isStructuredVideoPrompt(value: unknown): value is VideoPrompt {
  if (!isRecord(value) || typeof value.action !== "string") {
    return false;
  }
  const dialogue = value.dialogue;
  if (dialogue === undefined) return true;
  if (!Array.isArray(dialogue)) return false;
  return dialogue.every(
    (item) =>
      isRecord(item) &&
      typeof item.speaker === "string" &&
      typeof item.line === "string",
  );
}

export function imagePromptBody({ scene, composition }: ImagePrompt): string {
  if (!composition) return scene;
  return [scene, ...([
    ["镜头", composition.shot_type], ["光线", composition.lighting], ["氛围", composition.ambiance],
  ] as const).flatMap(([label, raw]) => {
    const value = raw?.trim();
    return value && !scene.includes(value) ? [`${label}：${value}`] : [];
  })].join("\n");
}

const timedSections = (text: string) => Array.from(text.matchAll(/^[ \t]*\[(\d{1,3})s-(\d{1,3})s\]/gm));

export function videoPromptBody({ action, camera_motion, ambiance_audio }: VideoPrompt): string {
  if (!camera_motion && !ambiance_audio) return action;
  const audio = ambiance_audio ?? "";
  const shots = timedSections(action);
  const sounds = timedSections(audio);
  const common = audio.slice(0, sounds[0]?.index ?? audio.length).trim();
  const addFields = (text: string, sound: string) => {
    let shot = text.trim();
    if (camera_motion) {
      const shotLine = /^(?:镜头|shot|camera(?: shot)?)[ \t]*[:：][^\n]*/im.exec(shot);
      const motion = /固定|推近|推进|拉远|后拉|摇镜|摇摄|平移|横移|跟拍|环绕|变焦|升降|手持|静止|缓推|缓拉|推拉|推镜|拉镜|\b(?:static|fixed|locked|pan|tilt|zoom|push in|pull out|truck|pedestal|orbit|track(?:ing)?|shake|dolly|handheld)\b/i;
      if (!shotLine) shot = [`镜头：${camera_motion}`, shot].filter(Boolean).join("\n");
      else if (!motion.test(shotLine[0]) && !/^(?:运镜|镜头运动|camera motion)[ \t]*[:：]/im.test(shot)) {
        const end = shotLine.index + shotLine[0].length;
        shot = `${shot.slice(0, end)}；运镜：${camera_motion}${shot.slice(end)}`;
      }
    }
    if (!sound || shot.includes(sound)) return shot;
    const soundField = /^(?:声音|音效|sound(?: effects?)?|audio)[ \t]*[:：][ \t]*([^\n]*)$/im;
    const line = `声音：${sound}`;
    if (soundField.test(shot)) {
      return shot.replace(soundField, (field, current: string) =>
        /^(?:无[。.]?|none[.]?)?$/i.test(current.trim()) ? line : `${field.trimEnd()}；${sound}`);
    }
    const speech = /^(?:台词|旁白|dialogue|voiceover)[ \t]*[:：]/im.exec(shot);
    return speech ? `${shot.slice(0, speech.index)}${line}\n${shot.slice(speech.index)}` : [shot, line].filter(Boolean).join("\n");
  };
  if (!shots.length) return addFields(action, audio.trim());
  const clipsByShot: string[][] = shots.map(() => []);
  sounds.forEach((span, i) => {
    const clip = audio.slice(span.index + span[0].length, sounds[i + 1]?.index).trim();
    if (!clip) return;
    const start = Number(span[1]);
    const end = Number(span[2]);
    let matched = false;
    shots.forEach((shot, j) => {
      if (start >= +shot[2] || end <= +shot[1]) return;
      clipsByShot[j].push(start === +shot[1] && end === +shot[2] ? clip : `${span[0].trim()} ${clip}`);
      matched = true;
    });
    if (!matched) {
      const following = shots.findIndex((shot) => start < +shot[1]);
      clipsByShot[following < 0 ? shots.length - 1 : following].push(`${span[0].trim()} ${clip}`);
    }
  });
  const blocks = shots.map((shot, i) => {
    const body = action.slice(shot.index + shot[0].length, shots[i + 1]?.index);
    return `${shot[0].trim()}\n${addFields(body, [common, ...clipsByShot[i]].filter(Boolean).join("；"))}`;
  });
  return [action.slice(0, shots[0].index).trim(), ...blocks].filter(Boolean).join("\n\n");
}

/** 文本形态切回结构化时的空结构：不解析原文本，字段留空由创作者重填。 */
export function emptyImagePrompt(): ImagePrompt {
  return { scene: "" };
}

/**
 * 同上；drama 的口播由分镜级 utterances 承载，其 video_prompt 不带 dialogue（后端
 * DramaVideoPrompt 在 extra="forbid" 下读时剥离该键），故 drama 分支断言到同一类型。
 */
export function emptyVideoPrompt(isDrama: boolean): VideoPrompt {
  const base = { action: "" };
  return isDrama ? (base as VideoPrompt) : { ...base, dialogue: [] };
}
