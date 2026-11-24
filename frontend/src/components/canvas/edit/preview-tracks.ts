/**
 * 剪辑视图里的音频与字幕轨道：把读取结果与预览素材层摆到全局时间上。全部是纯函数。
 *
 * 字幕的摆放与剪映草稿同口径（backend/lib/jianying_draft/placement.py）：跟随旁白的字幕只挂在承载旁白的片段上，
 * 其余字幕按视频源素材时间保留、只显示落在入出点之内的部分；同一时刻只显示一条，后一条开始时前一条截止。
 */

import type { EditTimelinePreviewMedia, EditTimelineReadout } from "@/types/edit-timeline";
import type { PreviewAspect } from "@/utils/preview-aspect";

import type { PlaybackPlan } from "./playback-schedule";

export const AUDIO_KINDS = ["narration", "dialogue", "sfx", "bgm"] as const;
export type AudioKind = typeof AUDIO_KINDS[number];

export interface AudioPlacement {
  id: string;
  editId: string;
  kind: AudioKind | "source";
  sourceId: string;
  unitId?: string;
  start: number;
  end: number;
  sourceIn: number;
  length: number;
  volume: number;
  fadeIn: number;
  fadeOut: number;
  name?: string | null;
  pictureAudio?: boolean;
  stem?: boolean;
  detachedStem?: boolean;
}

export type AudioRow = { id: string; kind: AudioKind; items: AudioPlacement[] };

export function audioRows(audio: readonly AudioPlacement[]) {
  const rows: AudioRow[] = [];
  const ordered = [...audio].sort((a, b) => a.start - b.start);
  for (const kind of AUDIO_KINDS) {
    const lanes: AudioPlacement[][] = [[]];
    for (const item of ordered) {
      if (item.kind !== kind) continue;
      const lane = lanes.find((items) => (items.at(-1)?.end ?? 0) <= item.start + 1e-7);
      if (lane) lane.push(item);
      else lanes.push([item]);
    }
    lanes.forEach((items, lane) => { if (items.length) rows.push({ id: `${kind}-${lane}`, kind, items }); });
  }
  return rows;
}

export interface PlacedSubtitle {
  id: string;
  start: number;
  end: number;
  text: string;
}

function round(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

function unitMediaOf(media: EditTimelinePreviewMedia | null) {
  return new Map((media?.units ?? []).map((unit) => [unit.unit_id, unit]));
}

export function clipAudioPlacements(
  readout: EditTimelineReadout,
  media: EditTimelinePreviewMedia | null,
): AudioPlacement[] {
  const units = unitMediaOf(media);
  const items: AudioPlacement[] = [];
  for (const clip of readout.clips) {
    if (clip.status === "unit_deleted") continue;
    const unit = units.get(clip.unit_id);
    const narration = clip.narration;
    if (narration && unit?.narration_audio) {
      const naturalEnd = narration.end ?? clip.start + clip.duration;
      const end = Math.min(naturalEnd, readout.duration);
      if (end > narration.start) items.push({
        id: `narration-${clip.id}`, editId: clip.id, kind: "narration", sourceId: clip.unit_id, unitId: clip.unit_id,
        start: narration.start, end, length: naturalEnd - narration.start, sourceIn: narration.source_in ?? 0,
        volume: 1, fadeIn: 0, fadeOut: 0,
      });
    }
    const available = clip.source_audio_duration;
    if (available == null || !unit?.provider_audio) continue;
    const trim = clip.trim?.basis_version === clip.video_version ? clip.trim : null;
    for (const kind of ["source", "dialogue", "sfx"] as const) {
      const override = kind === "source" ? clip.source_audio : clip[`${kind}_audio`];
      const window = override ?? clip.source_audio;
      if (window === false || (kind === "source" && (clip.dialogue_audio != null || clip.sfx_audio != null))) continue;
      const start = window ? window.start_us / 1e6 : clip.start;
      const sourceIn = window ? window.source_in_us / 1e6 : trim?.source_in ?? 0;
      const sourceOut = Math.min(available, window ? Infinity : trim?.source_out ?? clip.source_duration ?? 0);
      const length = Math.min(sourceOut - sourceIn, window ? window.duration_us / 1e6 : Infinity);
      const end = Math.min(readout.duration, start + length);
      if (end > start) items.push({
        id: kind === "source" ? `source-${clip.id}` : `${kind}-source-${clip.id}`,
        editId: clip.id, kind, sourceId: clip.id, unitId: clip.unit_id,
        start, end, length, sourceIn, volume: clip.source_volume, fadeIn: 0, fadeOut: 0,
        pictureAudio: kind === "source" && window == null,
        stem: kind !== "source", detachedStem: kind !== "source" && override != null,
      });
    }
  }
  return items;
}

/**
 * BGM 片段按读取结果的实际起止与淡入淡出摆放（截断与淡入淡出的收缩由服务端算好，与成片、剪映草稿同一份摆放）。
 * 音量是片段音量乘以 BGM 的响度增益；预览素材层还没有这首 BGM 时按片段音量摆放，只显示在轨上、不出声。
 */
export function bgmPlacements(
  readout: EditTimelineReadout,
  media: EditTimelinePreviewMedia | null,
): AudioPlacement[] {
  const gains = new Map((media?.bgm ?? []).map((item) => [item.bgm_id, item.gain]));
  return readout.bgm.flatMap((item) => {
    if (item.end <= item.start) return [];
    return [
      {
        id: `bgm-${item.id}`,
        editId: item.id,
        kind: item.kind ?? "bgm",
        length: item.source_out - item.source_in,
        sourceId: item.bgm_id,
        name: item.name,
        start: item.start,
        end: item.end,
        sourceIn: item.source_in,
        volume: round(item.volume * (gains.get(item.bgm_id) ?? 1)),
        fadeIn: item.fade_in,
        fadeOut: item.fade_out,
      },
    ];
  });
}

/** 字幕摆到全局时间。只有可播放视频的片段带字幕；呈现模型物化不出的单元没有字幕条目。 */
export function placeSubtitles(
  readout: EditTimelineReadout,
  plan: PlaybackPlan,
  media: EditTimelinePreviewMedia | null,
): PlacedSubtitle[] {
  if (readout.subtitles != null) {
    return readout.subtitles.flatMap((item) => {
      const start = item.start_us / 1e6;
      const end = Math.min(plan.duration, item.end_us / 1e6);
      return end > start ? [{ id: item.id, start, end, text: item.text }] : [];
    });
  }
  const units = unitMediaOf(media);
  const clips = new Map(readout.clips.map((clip) => [clip.id, clip]));
  const placed: PlacedSubtitle[] = [];
  for (const segment of plan.segments) {
    const unit = units.get(segment.unitId);
    const clip = clips.get(segment.clipId);
    if (!segment.hasVideo || !unit || !clip) continue;
    if (unit.subtitles_follow_narration) {
      if (!clip.carries_narration) continue;
      unit.subtitles.forEach((cue, index) => {
        placed.push({ id: `${clip.id}:${index}`, start: round(segment.start + cue.start), end: round(segment.start + cue.start + cue.duration), text: cue.text });
      });
      continue;
    }
    unit.subtitles.forEach((cue, index) => {
      const start = Math.max(cue.start, segment.sourceIn);
      const end = Math.min(cue.start + cue.duration, segment.sourceOut);
      if (end > start) {
        placed.push({
          id: `${clip.id}:${index}`,
          start: round(segment.start + start - segment.sourceIn),
          end: round(segment.start + end - segment.sourceIn),
          text: cue.text,
        });
      }
    });
  }
  placed.sort((a, b) => a.start - b.start);
  return placed.flatMap((item, index) => {
    const limit = index + 1 < placed.length ? placed[index + 1].start : plan.duration;
    const end = Math.min(item.end, limit, plan.duration);
    return end > item.start ? [{ ...item, end }] : [];
  });
}

/** 全局时间 `t` 上显示的字幕；没有时为 null。 */
export function subtitleAt(subtitles: readonly PlacedSubtitle[], t: number): PlacedSubtitle | null {
  let low = 0;
  let high = subtitles.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (subtitles[middle].end <= t) low = middle + 1;
    else high = middle;
  }
  const item = subtitles[low];
  return item && t >= item.start ? item : null;
}

export interface SubtitleLayout {
  /** 字号，以画面短边的百分比计。 */
  fontSizePercentOfShortSide: number;
  /** 字幕中心距画面顶部的百分比。 */
  centerFromTopPercent: number;
  /** 最大行宽，以画面宽度的百分比计。 */
  maxWidthPercent: number;
}

/**
 * 字幕在预览画面上的近似位置与字号，按剪映草稿的字幕样式（backend/lib/jianying_draft/archive.py `_subtitle_style`）换算：
 * 竖屏字号 12、横屏字号 8，剪映字号 1 约等于 1080 短边上的 5px；纵向偏移 -0.75 / -0.8 是相对画面中心、以半高为单位；
 * 行宽 0.82 / 0.6 是画面宽度的比例。字体用系统黑体粗体近似。
 */
export function subtitleLayout(aspect: PreviewAspect): SubtitleLayout {
  const portrait = aspect === "9:16";
  const size = portrait ? 12 : 8;
  const offset = portrait ? 0.75 : 0.8;
  return {
    fontSizePercentOfShortSide: round(((size * 5) / 1080) * 100),
    centerFromTopPercent: round(50 + offset * 50),
    maxWidthPercent: portrait ? 82 : 60,
  };
}
