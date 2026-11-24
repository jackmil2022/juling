"""
Prompt 工具函数

提供结构化 Prompt 到 YAML 格式的转换功能。
"""

import logging
import re
from collections.abc import Mapping, Sequence
from textwrap import indent
from typing import Any, get_args

import yaml

from lib.prompts.minimax import h3_reference_slot, is_minimax_media_model, minimax_media_prompt
from lib.project.asset_types import asset_name_comparison_key, normalize_asset_bucket, normalize_asset_name
from lib.prompts.prompt_style import normalize_style_value
from lib.prompts.prompt_templates.builtin import builtin_templates
from lib.prompts.reference_image_numbering import REFERENCE_IMAGES_KEY
from lib.script.reference_video.text_parser import UNIT_TIME_RANGE, format_prompt_timeline, render_mentions, split_speech_line
from lib.script.script_models import CameraMotion, ShotType

logger = logging.getLogger(__name__)

# 提示词 YAML 的行宽上限。PyYAML 默认 80 列，超宽的纯量会在 ASCII 空格处折成多行——
# 英文 / 越南语提示词几乎每个值都超 80 列，折行会把原文塞进换行再喂给供应商。取一个任何
# 提示词都达不到的值，值内容与作者所写逐字一致。
_PROMPT_YAML_WIDTH = 1_000_000


def _dump_prompt_yaml(ordered: Mapping[str, Any]) -> str:
    """提示词各段共用的 YAML 序列化：键序保持插入序、Unicode 原样、块式布局、不折行。"""
    return yaml.dump(
        dict(ordered),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=_PROMPT_YAML_WIDTH,
    )


# 提示词正文里的排除项行：``Avoid:`` 顶行起，前缀后是本行的排除项措辞。识别按前缀而非整行——
# 纯文本回贴带回来的可能是任一历史版本的完整声明（如不含 Logo 的旧行），整行比对只认得出被写死
# 的那一版。冒号后只吃空格与制表符，换行不进前缀。
_AVOID_LINE = re.compile(r"^Avoid:[ \t]*(.*)$")

# 排除项拼接与追加到负向节点字面值时的分隔符。
_AVOID_SEPARATOR = "，"

# 正文里连续空行的塌缩上限：删掉 Avoid 行后留下的空行按此并成一个，与模版引擎对自身产生的连续
# 换行所做的塌缩同一口径。
_BLANK_RUN = re.compile(r"\n{3,}")

# 预设选项：真相源是 lib.script.script_models 的 Literal 词表，此处派生避免双写漂移
SHOT_TYPES: list[str] = list(get_args(ShotType))
CAMERA_MOTIONS: list[str] = list(get_args(CameraMotion))


def image_prompt_to_yaml(
    image_prompt: dict, project_style: str, *, reference_images: Sequence[str] = (), style_description: str = ""
) -> str:
    """
    将 imagePrompt 结构转换为 YAML 格式字符串

    Args:
        image_prompt: segment 中的 image_prompt 对象，结构为：
            {"scene": "含镜头、光线、氛围的场景描述"}
        project_style: 项目级风格设置（从 project.json 读取）
        reference_images: 按上传顺序排列的参考图名称与用途，非空时作为
            ``Reference_Images`` 键插在风格块与 ``Scene`` 之间
        style_description: 项目风格描述

    Returns:
        YAML 格式字符串，键序 Style / Visual style / Reference_Images / Scene / Visual requirements
    """
    scene = image_prompt["scene"].rstrip()
    body = f"Scene: |-\n{indent(scene, '  ')}" if "\n" in scene else yaml_section({"Scene": scene})
    return (
        builtin_templates.render(
            "storyboard/image",
            style=normalize_style_value(project_style),
            style_description=normalize_style_value(style_description),
            reference_images=yaml_section({REFERENCE_IMAGES_KEY: list(reference_images)}) if reference_images else "",
            structured_body=body,
            text_body="",
        )
        + "\n"
    )


def require_storyboard_scene(image_prompt: Mapping[str, Any]) -> str:
    """Return the trimmed ``scene`` of a structured storyboard prompt, or raise ``ValueError``.

    Single criterion for what counts as a usable ``scene``: the enqueue guard
    (``TaskSpec.from_request``) and the rendering projection below both call it, so a prompt
    accepted at submission is exactly one the renderer can project.
    """

    scene = image_prompt.get("scene")
    if not isinstance(scene, str) or not scene.strip():
        raise ValueError("image_prompt.scene must be a non-empty string")
    return scene.strip()


def project_storyboard_image_prompt(image_prompt: object, project_style: str) -> tuple[str | dict[str, Any], str]:
    """Project one script prompt into the canonical semantics shared by rendering and currency."""

    if isinstance(image_prompt, str):
        prompt = image_prompt.strip()
        if not prompt:
            raise ValueError("image_prompt must not be empty")
        return prompt, project_style
    if not isinstance(image_prompt, Mapping):
        raise ValueError("image_prompt must be a string or object")
    scene = require_storyboard_scene(image_prompt)
    raw_composition = image_prompt.get("composition")
    composition = raw_composition if isinstance(raw_composition, Mapping) else {}
    lines = [scene]
    for key, label in (("shot_type", "镜头"), ("lighting", "光线"), ("ambiance", "氛围")):
        if (value := str(composition.get(key) or "").strip()) and value not in scene:
            lines.append(f"{label}：{value}")
    return {"scene": "\n".join(lines)}, project_style


_SHOT_FIELD = re.compile(r"(?im)^(?:镜头|shot|camera(?: shot)?)[ \t]*[:：][^\n]*")
_MOTION_FIELD = re.compile(r"(?im)^(?:运镜|镜头运动|camera motion)[ \t]*[:：]|固定|推近|推进|拉远|后拉|摇镜|摇摄|平移|横移|跟拍|环绕|变焦|升降|手持|静止|缓推|缓拉|推拉|推镜|拉镜|\b(?:static|fixed|locked|pan|tilt|zoom|push in|pull out|truck|pedestal|orbit|track(?:ing)?|shake|dolly|handheld)\b")
_SOUND_FIELD = re.compile(r"(?im)^(?:声音|音效|sound(?: effects?)?|audio)[ \t]*[:：][ \t]*([^\n]*)$")
_EMPTY_SOUND = re.compile(r"(?:无[。.]?|none[.]?)?", re.I)
_SPEECH_FIELD = re.compile(r"(?im)^(?:台词|旁白|dialogue|voiceover)[ \t]*[:：]")
_SPEECH_SUFFIX = re.compile(r"(?m)^(?:Dialogue|Voiceover):")
_VOICEOVER_SECTION = re.compile(r"(?m)(?:\A|(?<=\n\n))Voiceover:[^\n]*(?:\n+[ \t]+[^\n]*)*")


def merge_video_prompt_body(action: str, motion: str = "", sound: str = "") -> str:
    """Read legacy side fields back into the timed shots without changing dialogue."""
    body = format_prompt_timeline(action)
    ranges = list(UNIT_TIME_RANGE.finditer(body))
    sound_ranges = list(UNIT_TIME_RANGE.finditer(sound))

    def add_fields(shot: str, audio: str) -> str:
        shot = shot.strip()
        if audio and audio not in shot:
            line = f"声音：{audio}"
            if sound_line := _SOUND_FIELD.search(shot):
                current = sound_line[1].strip()
                merged = line if _EMPTY_SOUND.fullmatch(current) else f"{sound_line[0].rstrip()}；{audio}"
                shot = shot[:sound_line.start()] + merged + shot[sound_line.end():]
            elif speech := _SPEECH_FIELD.search(shot):
                shot = f"{shot[:speech.start()]}{line}\n{shot[speech.start():]}"
            else:
                shot = "\n".join(part for part in (shot, line) if part)
        if motion:
            shot_line = _SHOT_FIELD.search(shot)
            if shot_line is None:
                return f"镜头：{motion}\n{shot}".rstrip()
            if not _MOTION_FIELD.search(shot_line[0]) and not re.search(r"(?im)^(?:运镜|镜头运动|camera motion)[ \t]*[:：]", shot):
                return f"{shot[:shot_line.end()]}；运镜：{motion}{shot[shot_line.end():]}"
        return shot

    if not ranges:
        return add_fields(body, sound.strip())
    blocks = [body[:ranges[0].start()].strip()]
    clips_by_shot: list[list[str]] = [[] for _ in ranges]
    shot_times = [(float(span[1]), float(span[2])) for span in ranges]
    for i, span in enumerate(sound_ranges):
        end = sound_ranges[i + 1].start() if i + 1 < len(sound_ranges) else len(sound)
        if clip := sound[span.end():end].strip():
            start, finish = float(span[1]), float(span[2])
            matching = [j for j, (a, b) in enumerate(shot_times) if start < b and finish > a]
            for j in matching or [next((j for j, (a, _) in enumerate(shot_times) if start < a), len(ranges) - 1)]:
                clips_by_shot[j].append(clip if (start, finish) == shot_times[j] else f"[{start:g}s-{finish:g}s] {clip}")
    common = (sound[:sound_ranges[0].start()] if sound_ranges else sound).strip()
    for i, span in enumerate(ranges):
        end = ranges[i + 1].start() if i + 1 < len(ranges) else len(body)
        audio = "；".join(filter(None, (common, *clips_by_shot[i])))
        blocks.append(f"{span[0].strip()}\n{add_fields(body[span.end():end], audio)}")
    return "\n\n".join(block for block in blocks if block)


def video_prompt_to_yaml(video_prompt: dict) -> str:
    """
    将 videoPrompt 结构转换为 YAML 格式字符串

    Args:
        video_prompt: segment 中的 video_prompt 对象，结构为：
            {
                "action": "动作描述",
                "camera_motion": "摄像机运动",
                "ambiance_audio": "环境音效描述",
                "voiceover": "旁白 / 口播文案（由当前分镜内容字段注入）",
                "dialogue": [{"speaker": "角色名", "line": "台词"}],
                "voice_profiles": [{"Speaker": "角色名", "Voice_Style": "声音风格"}]
            }

    Returns:
        YAML 格式字符串，以 ``Avoid`` 反向约束键收尾
    """
    dialogue = [{"Speaker": d["speaker"], "Line": d["line"]} for d in video_prompt.get("dialogue", [])]
    voice_profiles = video_prompt.get("voice_profiles") or []
    voiceover = str(video_prompt.get("voiceover") or "").strip()

    ordered: dict[str, Any] = {}
    # Voice_Profiles 是集中声明段，须在顶部：调用方已按 dialogue speaker ∩ 非空 voice_style
    # 角色资产派生好列表，此处只负责按序注入，不做二次过滤。
    if voice_profiles:
        ordered["Voice_Profiles"] = voice_profiles
    prefix = _dump_prompt_yaml(ordered).rstrip() if ordered else ""
    action = merge_video_prompt_body(video_prompt["action"], video_prompt["camera_motion"], video_prompt["ambiance_audio"])
    ordered = {}
    if voiceover:
        ordered["Voiceover"] = voiceover

    # 仅在有对话时添加 Dialogue 字段
    if dialogue:
        ordered["Dialogue"] = dialogue
    suffix = _dump_prompt_yaml(ordered).rstrip() if ordered else ""
    body = "\n\n".join(part for part in (prefix, action, suffix) if part)
    return builtin_templates.render("storyboard/video", body=body) + "\n"


def normalize_video_prompt(prompt: object) -> str:
    """Normalize the exact text sent to a video provider."""

    if isinstance(prompt, str):
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        body, _ = split_avoid_lines(prompt)
        return builtin_templates.render("storyboard/video", body=body.rstrip())
    if not isinstance(prompt, dict):
        raise ValueError("prompt must be a string or object")
    if not is_structured_video_prompt(prompt):
        raise ValueError("prompt must be a string or include action")

    action_text = str(prompt.get("action", "")).strip()
    if not action_text:
        raise ValueError("prompt.action must not be empty")
    dialogue = prompt.get("dialogue", [])
    if dialogue is None:
        dialogue = []
    if not isinstance(dialogue, list):
        raise ValueError("prompt.dialogue must be an array")

    normalized_dialogue = []
    for item in dialogue:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "") or "").strip()
        line = str(item.get("line", "") or "").strip()
        if speaker or line:
            normalized_dialogue.append({"speaker": speaker, "line": line})

    normalized_prompt: dict[str, Any] = {
        "action": action_text,
        "camera_motion": str(prompt.get("camera_motion") or ""),
        "ambiance_audio": str(prompt.get("ambiance_audio", "") or ""),
        "voiceover": str(prompt.get("voiceover", "") or "").strip(),
        "dialogue": normalized_dialogue,
        "voice_profiles": prompt.get("voice_profiles") or [],
    }
    return video_prompt_to_yaml(normalized_prompt).rstrip()


def render_storyboard_video_prompt(
    prompt: object,
    item: object | None = None,
    *,
    content_mode: str,
    voice_characters: dict[str, Any] | None,
    model: str = "",
    references: Sequence[tuple[str, str]] = (),
    preserve_mentions: bool = False,
) -> str:
    """分镜生视频最终提示词文本的唯一出口。

    执行路径、批量准入、执行敏感摘要与预览接口共用本函数，四处产出逐字同构由此在结构上
    成立，而非各写一份靠约定对齐。``prompt`` 取条目当前的 ``video_prompt``（结构形态或文本
    形态），``item`` 提供当前分镜的旁白字段与 drama 的 ``utterances``（``None`` 视同无条目）。

    文本形态下条目正文即模版的正文槽位；``Voiceover`` 由本函数从当前分镜内容字段
    注入并限定在分镜正文的时段内，交给视频模型直接生成声音。drama 的角色台词与声音风格仍由脚本规划的
    ``utterances`` 决定，角色台词和 ``Voiceover`` 都在最终提示词中按同一出口追加。
    """

    uses = {
        "character": "角色「{name}」的脸、发型与服装参考",
        "scene": "场景「{name}」的空间布局、朝向与环境参考",
        "prop": "道具「{name}」的形状、材质与细节参考",
        "product": "商品「{name}」的外观、比例与正反面参考",
    }
    slots: dict[str, list[str]] = {}
    declarations = []
    for index, (kind, name) in enumerate(references, 1):
        slot = "参考" + h3_reference_slot("image", index)
        slots.setdefault(asset_name_comparison_key(name), []).append(slot)
        declarations.append(f"{slot}是{uses[kind].format(name=name)}。")

    def bind(name: str) -> str:
        matches = slots.get(asset_name_comparison_key(name), [])
        return f"{name}（{matches[0]}）" if len(matches) == 1 else name

    names = sorted((name for name, matches in slots.items() if len(matches) == 1), key=len, reverse=True)
    bare_names = re.compile("|".join(
        (r"(?<![A-Za-z0-9_])" if name[0].isascii() and name[0].isalnum() else "") + re.escape(name)
        + (r"(?![A-Za-z0-9_])" if name[-1].isascii() and name[-1].isalnum() else "")
        for name in names
    )) if names else None

    def bind_plain(text: str) -> str:
        return bare_names.sub(lambda match: bind(match[0]), text) if bare_names is not None else text

    def bind_line(line: str) -> str:
        if preserve_mentions:
            return line
        if _SPEECH_FIELD.match(line):
            return "".join(
                part if isinstance(part, str) else f"{bind(part.speaker_reference)}说：{part.text}"
                if part.speaker_reference else part.raw for part in split_speech_line(line)
            )
        return "".join(
            render_mentions(part, bind, render_plain=bind_plain) if isinstance(part, str) else part.raw
            for part in split_speech_line(line)
        )

    duration = _item_field(item, "duration_seconds")

    def render_action(text: str) -> str:
        if references and text.strip() and not UNIT_TIME_RANGE.search(text) and type(duration) in (int, float) and duration > 0:
            text = f"[0s-{duration:g}s]\n{text}"
        return "\n".join(bind_line(line) for line in format_prompt_timeline(text).splitlines())

    action = ""
    if isinstance(prompt, str):
        prompt = prompt.replace("\r\n", "\n")
        speech = _SPEECH_SUFFIX.search(prompt)
        action = render_action(prompt[:speech.start()] if speech else prompt)
        if speech:
            prompt = f"{action}\n\n{prompt[speech.start():]}"
        else:
            prompt = action
    elif isinstance(prompt, dict) and isinstance(prompt.get("action"), str):
        action = render_action(prompt["action"])
        prompt = {**prompt, "action": action}
    voiceover = _item_voiceover_text(item, content_mode)
    if voiceover:
        end = max((float(match[2]) for match in UNIT_TIME_RANGE.finditer(action)), default=0.0)
        if type(duration) in (int, float) and duration > 0:
            end = min(end, duration) if end else duration
        if end:
            voiceover = f"[0s-{end:g}s] {voiceover}"
    if isinstance(prompt, dict):
        prompt = strip_voice_profiles(prompt)
        if voiceover:
            prompt = {**prompt, "voiceover": voiceover}
        if content_mode == "drama":
            utterances = _item_field(item, "utterances", _ITEM_FIELD_MISSING)
            if utterances is not _ITEM_FIELD_MISSING:
                prompt = build_drama_video_prompt(prompt, utterances, characters=voice_characters)
            else:
                # utterances 迁移前的存量剧本：load_script 按原始 JSON 读盘不过 pydantic，不会被
                # DramaScene._migrate_legacy 自动补齐，台词仍留在 video_prompt.dialogue。
                prompt = build_drama_video_prompt_from_legacy_dialogue(prompt, characters=voice_characters)
    elif isinstance(prompt, str):
        prompt = _attach_voiceover_text(prompt, voiceover)
        if content_mode == "drama":
            prompt = _attach_drama_speech_text(prompt, item, characters=voice_characters)
    if isinstance(prompt, str) and is_minimax_media_model(model):
        # Retain the existing custom exclusion line until the positive rewrite consumes it.
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        prompt = builtin_templates.render("storyboard/video", body=prompt.rstrip())
    else:
        prompt = normalize_video_prompt(prompt)
    if declarations:
        prompt = "\n".join(declarations) + "\n\n" + prompt
    return minimax_media_prompt(prompt, model, video=True)


_ITEM_FIELD_MISSING = object()


def _item_field(item: object | None, field: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _item_voiceover_text(item: object | None, content_mode: str) -> str:
    """从分镜条目提取最终交给视频模型的旁白文本。

    条目可能来自原始 JSON ``dict``，也可能是已实例化的 Pydantic 对象。drama 保留
    ``utterances`` 的原顺序，只取非空 ``voiceover`` 条目；其他模式各取自己的一等文本字段。
    """
    field_by_mode = {"ad": "voiceover_text", "narration": "novel_text"}
    if content_mode in field_by_mode:
        value = _item_field(item, field_by_mode[content_mode])
        return value.strip() if isinstance(value, str) else ""
    if content_mode != "drama":
        return ""

    utterances = _item_field(item, "utterances")
    if not isinstance(utterances, list):
        return ""
    texts: list[str] = []
    for utterance in utterances:
        if _item_field(utterance, "kind") != "voiceover":
            continue
        value = _item_field(utterance, "text")
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return "\n".join(texts)


def _attach_voiceover_text(text: str, voiceover: str) -> str:
    if not voiceover:
        return text
    section = yaml_section({"Voiceover": voiceover})
    if _VOICEOVER_SECTION.search(text):
        return _VOICEOVER_SECTION.sub(lambda _: section, text, count=1)
    return f"{text.rstrip()}\n\n{section}\n"


def _attach_drama_speech_text(text: str, item: object | None, *, characters: dict[str, Any] | None) -> str:
    """把 drama 的发声声明段追加到文本形态 video_prompt 正文之后。

    与结构形态共用 ``utterances_to_dialogue`` 与 ``_build_voice_profiles``，键名沿用
    ``video_prompt_to_yaml`` 的 ``Voice_Profiles`` / ``Dialogue``，两种形态对模型同一套词表。
    无台词、或无声门控下无声音风格可注入时不追加任何内容。两个声明段各自按内容判重：
    「结构化 → 文本」以当前渲染结果为初值，正文里已带着它们，整体判前缀会漏判而叠出第二份。
    """
    utterances = _item_field(item, "utterances")
    dialogue = utterances_to_dialogue(utterances)
    sections: list[str] = []
    if characters is not None:
        voice_profiles = _build_voice_profiles(dialogue, characters)
        if voice_profiles:
            sections.append(yaml_section({"Voice_Profiles": voice_profiles}))
    if dialogue:
        sections.append(
            yaml_section({"Dialogue": [{"Speaker": entry["speaker"], "Line": entry["line"]} for entry in dialogue]})
        )
    pending = [section for section in sections if section not in text]
    if not pending:
        return text
    return f"{text.rstrip()}\n\n" + "\n".join(pending) + "\n"


def split_avoid_lines(text: str) -> tuple[str, str]:
    """把提示词正文里的排除项行拆出来，返回 ``(正文, 排除项文本)``。

    正文里的 ``Avoid:`` 行是各通道共享的排除项声明，由模版按产出媒体注入。ComfyUI 仅在有可写的
    负向提示词绑定时拆出这些行单独填，没有入口时保留原文。

    正文按行去掉全部排除项行后，连续空行塌缩成一个、首尾空白去掉——被删的行常自带前后空行，
    不塌缩会在正文中间留下一段空白。排除项文本按出现顺序以「，」拼接，逐行去掉前缀后的措辞
    原样保留，空措辞的行不进拼接（它只是个孤零零的 ``Avoid:``）。
    """
    kept: list[str] = []
    avoided: list[str] = []
    for line in text.split("\n"):
        match = _AVOID_LINE.match(line)
        if match is None:
            kept.append(line)
            continue
        phrase = match.group(1).strip()
        if phrase:
            avoided.append(phrase)
    body = _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()
    return body, _AVOID_SEPARATOR.join(avoided)


def append_avoid_text(literal: str, avoid_text: str) -> str:
    """把拆出的排除项文本追加到负向节点的字面值之后。

    追加而不覆盖：workflow 作者写在负向节点里的措辞是这份 workflow 的一部分（触发词、质量
    词），抹掉它等于改写作者的底稿。字面值为空时直接写入，不留一个前导分隔符。
    """
    if not literal.strip():
        return avoid_text
    if not avoid_text:
        return literal
    return f"{literal}{_AVOID_SEPARATOR}{avoid_text}"


def normalize_image_prompt(text: str) -> str:
    """Keep legacy image exclusions as instructions in the main prompt."""
    if not any(_AVOID_LINE.match(line) for line in text.splitlines()):
        return text
    body, exclusions = split_avoid_lines(text)
    if not exclusions:
        return body
    return f"{body}\n\nKeep the image free of {exclusions}.".lstrip()


def yaml_section(ordered: dict[str, Any]) -> str:
    """渲染一个可独立追加到文本形态提示词的 YAML 段（无尾随换行）。

    键名与缩进沿用 ``image_prompt_to_yaml`` / ``video_prompt_to_yaml``：发声声明段、参考图类型
    声明行在结构形态与文本形态下逐字同形，文本形态才能按内容判重。
    """
    return _dump_prompt_yaml(ordered).rstrip()


def strip_voice_profiles(video_prompt: dict[str, Any]) -> dict[str, Any]:
    """剥离入参自带的 ``voice_profiles`` 键。

    ``Voice_Profiles`` 声明段由编排层从角色资产机械派生，剧本 JSON / 调用方请求体均不
    承载它——两处注入点（worker 执行路径、SDK 入队路径）在决定是否调用
    :func:`build_drama_video_prompt` 之前都须先过一遍本函数，drama 之外的 content_mode
    或缺 ``utterances`` 的条目才不会让调用方自带（或剧本残留）的 ``voice_profiles`` 绕过
    C 类（真无声）门控直接进入 YAML。
    """
    return {k: v for k, v in video_prompt.items() if k != "voice_profiles"}


def build_drama_video_prompt(
    video_prompt: dict[str, Any],
    utterances: object,
    *,
    characters: dict[str, Any] | None,
) -> dict[str, Any]:
    """drama video_prompt 的 dialogue 与 Voice_Profiles 唯一注入出口。

    worker 执行路径与 SDK 入队路径共用本函数，两处注入点的产出同构由此在结构上成立，而非
    各写一份靠约定对齐。

    ``characters`` 为 ``None`` 表示不注入 Voice_Profiles（C 类真无声模型）。无论注入
    与否都先剥离入参自带的 ``voice_profiles``：该声明段由编排层从角色资产机械派生，剧本
    JSON 不承载它，剧本中的残留值不得绕过 C 类门控进入 YAML。
    """
    prompt = strip_voice_profiles(video_prompt)
    dialogue = utterances_to_dialogue(utterances)
    return _attach_voice_profiles(prompt, dialogue, characters=characters)


def build_drama_video_prompt_from_legacy_dialogue(
    video_prompt: dict[str, Any],
    *,
    characters: dict[str, Any] | None,
) -> dict[str, Any]:
    """legacy drama 场景（utterances 迁移前的旧剧本，台词仍留在 ``video_prompt.dialogue``、
    无分镜级 ``utterances`` 字段）的 Voice_Profiles 注入出口。

    ``load_script`` 按原始 JSON 读盘、不过 pydantic，这类存量剧本不会被
    ``DramaScene._migrate_legacy`` 自动补齐 ``utterances``；调用方须按 ``"utterances" not
    in item`` 识别后改走本函数，而非 :func:`build_drama_video_prompt`——旧结构的
    ``dialogue`` 已是 ``{speaker, line}`` 目标形态，无需 :func:`utterances_to_dialogue`
    转换，直接派生 Voice_Profiles。
    """
    prompt = strip_voice_profiles(video_prompt)
    dialogue = prompt.get("dialogue")
    if not isinstance(dialogue, list):
        dialogue = []
    return _attach_voice_profiles(prompt, dialogue, characters=characters)


def _attach_voice_profiles(
    prompt: dict[str, Any], dialogue: list[dict[str, str]], *, characters: dict[str, Any] | None
) -> dict[str, Any]:
    prompt["dialogue"] = dialogue
    if characters is not None:
        voice_profiles = _build_voice_profiles(dialogue, characters)
        if voice_profiles:
            prompt["voice_profiles"] = voice_profiles
    return prompt


def _build_voice_profiles(dialogue: list[Any], characters: dict[str, Any]) -> list[dict[str, str]]:
    """从 dialogue speakers 与角色资产派生 Voice_Profiles 声明段。

    仅收录角色资产存在且 ``voice_style`` 非空者，一个 speaker 一条（按 dialogue 中首次
    出现的顺序去重）；speaker 未命中角色资产或资产 ``voice_style`` 为空，静默跳过
    （不建面向用户的提示通道，调用方按需记 logger）。

    speaker 与角色表 key 可能是 NFC/NFD 中的任一形态（存量剧本/桶无需迁移），按
    ``lib.project.asset_types`` 的比对坐标系归一后索引与去重，``Speaker`` 展示值保留 dialogue 原文。

    ``characters`` 来自明文 project.json，用户手编或外部脚本可能写成非 dict，逐层做类型
    收窄而非直接下标（同 ``lib.config.resolver._safe_dict`` 的取向）。
    """
    characters = normalize_asset_bucket(characters)
    seen: set[str] = set()
    profiles: list[dict[str, str]] = []
    for entry in dialogue:
        speaker = entry.get("speaker") if isinstance(entry, dict) else None
        if not isinstance(speaker, str) or not speaker:
            continue
        speaker_key = normalize_asset_name(speaker)
        if speaker_key in seen:
            continue
        seen.add(speaker_key)
        character = characters.get(speaker_key)
        if not isinstance(character, dict):
            logger.debug("Voice_Profiles 跳过：speaker %r 未命中角色资产", speaker)
            continue
        voice_style = character.get("voice_style")
        if isinstance(voice_style, str) and voice_style.strip():
            profiles.append({"Speaker": speaker, "Voice_Style": voice_style.strip()})
        else:
            logger.debug("Voice_Profiles 跳过：角色 %r 的 voice_style 为空", speaker)
    return profiles


def utterances_to_dialogue(utterances: object) -> list[dict[str, str]]:
    """drama 口型音轨出口：从有序 ``utterances`` 取 dialogue-kind 条目，转成 video YAML 的
    ``{speaker, line}`` 列表（保留时序）。

    voiceover-kind 不进入 ``Dialogue``，其文本由 ``_item_voiceover_text`` 进入最终 ``Voiceover``。
    对脏数据稳健：非 list 整体、非 dict/object 元素、非 dialogue 条目一律跳过；dialogue 须 speaker
    与 line 同时非空才进口型音轨，
    缺 speaker 的脏 dialogue（契约要求 dialogue 必带非空 speaker）不重新喂给 lip-sync / video prompt。

    兼容两种条目形态：原始 JSON ``dict`` 与已实例化的 Pydantic ``Utterance`` 模型对象（取同名属性）。
    speaker / text 用 ``isinstance(_, str)`` 显式取值，非字符串（如数字）按空处理、不 ``str()`` 强转，
    避免脏类型被静默字符串化进 YAML。
    """
    dialogue: list[dict[str, str]] = []
    if not isinstance(utterances, list):
        return dialogue
    for entry in utterances:
        if isinstance(entry, dict):
            kind = entry.get("kind")
            speaker_val = entry.get("speaker")
            text_val = entry.get("text")
        elif hasattr(entry, "kind"):
            kind = getattr(entry, "kind", None)
            speaker_val = getattr(entry, "speaker", None)
            text_val = getattr(entry, "text", None)
        else:
            continue

        if kind != "dialogue":
            continue

        speaker = speaker_val.strip() if isinstance(speaker_val, str) else ""
        line = text_val.strip() if isinstance(text_val, str) else ""
        if speaker and line:
            dialogue.append({"speaker": speaker, "line": line})
    return dialogue


def is_structured_image_prompt(image_prompt) -> bool:
    """
    检查 image_prompt 是否为结构化格式

    Args:
        image_prompt: image_prompt 字段值

    Returns:
        True 如果是结构化格式（dict），False 如果是旧的字符串格式
    """
    return isinstance(image_prompt, dict) and "scene" in image_prompt


def is_structured_video_prompt(video_prompt) -> bool:
    """
    检查 video_prompt 是否为结构化格式

    Args:
        video_prompt: video_prompt 字段值

    Returns:
        True 如果是结构化格式（dict），False 如果是旧的字符串格式
    """
    return isinstance(video_prompt, dict) and "action" in video_prompt


def validate_shot_type(shot_type: str) -> bool:
    """验证镜头类型是否为预设选项"""
    return shot_type in SHOT_TYPES


def validate_camera_motion(camera_motion: str) -> bool:
    """验证摄像机运动是否为预设选项"""
    return camera_motion in CAMERA_MOTIONS
