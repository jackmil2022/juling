"""Positive, natural-language prompts for MiniMax media models."""

import re

_VIDEO_REFERENCE_LINE = re.compile(r"(?im)^[ \t]*(?:参考视频|reference videos?)[ \t]*[:：][ \t]*([^\n]*)$")
_UNIT_ID = re.compile(r"E[1-9]\d*U[1-9]\d*", re.I)
_H3_SLOT = re.compile(r"<(?P<tag>Picture|Video|Audio)\s+(?P<tag_no>[1-9]\d*)>|(?P<ref>参考)?@?(?P<kind>图片|图|视频|音频)\s*(?P<no>[1-9]\d*)", re.I)
_H3_KIND = {"图片": "image", "图": "image", "视频": "video", "音频": "audio",
            "picture": "image", "video": "video", "audio": "audio"}
_H3_SLOT_NAMES = {"image": ("图", "Picture"), "video": ("视频", "Video"), "audio": ("音频", "Audio")}
_NEGATIVE_LINE = re.compile(r"(?im)^[ \t]*(?:avoid|negative[ _-]?prompt|负面提示词|负向提示词|反向提示词|排除项)\s*[:：][ \t]*([^\n]*)$")
_IMAGE_REQUIREMENTS = "画面干净，只呈现正文要求的视觉元素；文字、字幕和标识仅在正文明确要求时出现，不叠加水印。"
_IMAGE_POSITIVE = "画面干净完整，只呈现正文指定的视觉元素与参考素材自带的文字、标识。"
_VIDEO_POSITIVE = "画面仅呈现正文指定的视觉元素与参考素材自带的文字、标识。声音聚焦正文指定的旁白、对白、环境声和动作音效。"
_POSITIVE_EQUIVALENTS = (
    (re.compile(r"模糊|低清|blur|low quality|low resolution", re.I), "画面清晰，主体对焦准确，细节锐利。"),
    (re.compile(r"畸形|多指|坏手|bad anatomy|extra fingers|deformed", re.I), "人物比例自然，双手结构准确，手指数量自然。"),
    (re.compile(r"抖动|闪烁|flicker|jitter|shaky", re.I), "画面稳定，运动连贯，曝光和色彩一致。"),
    (re.compile(r"画面噪点|grainy|visual noise", re.I), "主体和背景纹理清晰。"),
    (re.compile(r"过曝|欠曝|overexpos|underexpos", re.I), "曝光均衡，亮部和暗部保留层次。"),
    (re.compile(r"分身|双胞胎|duplicate", re.I), "每位角色具有独立可辨的外貌和着装，同一角色在镜头中保持身份一致。"),
)


def is_minimax_media_model(model: str) -> bool:
    name = model.casefold()
    return name.startswith("minimax-") or name in {"image-01", "image-01-live", "s2v-01"} or "hailuo" in name


def is_minimax_h3_video(model: str) -> bool:
    return model.casefold() in {"minimax-h3", "minimax-h3-highspeed", "minimax-h3-lite", "minimax-h3-max"}


def is_minimax_h3_image(model: str) -> bool:
    return model.casefold() in {"minimax-h3-image", "minimax-h3-image-highspeed"}


def has_h3_video_reference_declaration(text: str) -> bool:
    return _VIDEO_REFERENCE_LINE.search(text) is not None


def split_h3_video_references(text: str) -> tuple[str, tuple[str, ...]]:
    """Extract same-episode video unit IDs, in provider attachment order."""
    declarations = _VIDEO_REFERENCE_LINE.findall(text)
    if not declarations:
        return text, ()
    ids = tuple(part.upper() for line in declarations for part in re.split(r"[\s、,，]+", line.strip()) if part)
    if not ids or len(ids) > 3 or not all(_UNIT_ID.fullmatch(item) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("参考视频须填写 1 至 3 个不同的单元编号，例如 `参考视频：E1U1、E1U2`。")
    return _VIDEO_REFERENCE_LINE.sub("", text).strip(), ids


def h3_reference_slot(kind: str, index: int, *, director: bool = False) -> str:
    native, tag = _H3_SLOT_NAMES[kind]
    return f"<{tag} {index}>" if director else f"{native}{index}"


def format_h3_reference_slots(
    text: str, *, director: bool = False, images: int = 0, videos: int = 0, audios: int = 0
) -> str:
    """Translate the numbered references only where they name actual Director input slots."""
    limits = {"image": images, "video": videos, "audio": audios}

    def render(match: re.Match[str]) -> str:
        kind = _H3_KIND[(match["tag"] or match["kind"]).casefold()]
        index = int(match["tag_no"] or match["no"])
        if director and index > limits[kind]:
            return match[0]
        prefix = "" if director else (match["ref"] or "")
        return prefix + h3_reference_slot(kind, index, director=director)

    return _H3_SLOT.sub(render, text)


def h3_continuity_instruction(slot: str, *, previous: bool, pika: bool) -> str:
    direction = ("是上一镜的续接依据。本镜从它最后一帧的状态起步，在上一镜的基础上沿时间向后扩展新动作，形成无缝衔接。"
                 "若本镜的开场描述与上一镜末尾冲突，接缝处优先延续上一镜的状态，再自然过渡到本镜指定的动作和机位"
                 if previous else "是下一镜的衔接目标。本镜结尾自然过渡到它第一帧的状态")
    return (f"{slot} {direction}。保持人物和物体的位置、比例、姿态、视线、动作方向与速度连续，"
            "机位、景别、构图、光线和色调逐步协调，环境声和对白音量平滑延续。"
            "动作与镜头运动顺势连接，避免突变和硬切，不重演参考片段。")


def h3_boundary_instruction(slot: str, *, first: bool) -> str:
    return f"{slot} {'匹配开场' if first else '匹配结尾'}的构图与主体。"


def minimax_media_prompt(text: str, model: str, *, video: bool) -> str:
    if not is_minimax_media_model(model):
        return text
    negatives: list[str] = []

    def collect_negative(match: re.Match[str]) -> str:
        negatives.append(match[1])
        return ""

    body = _NEGATIVE_LINE.sub(collect_negative, text)
    body = body.replace("Visual requirements: " + _IMAGE_REQUIREMENTS, _IMAGE_POSITIVE)
    if video and is_minimax_h3_video(model):
        body = re.sub(r"<([^<>\n]+)>@图片(\d+)", r"「\1」参考图\2", body)
        body = format_h3_reference_slots(body)
    # Keep output idempotent when a user copies the rendered prompt back into an editor.
    statements = [_VIDEO_POSITIVE if video else _IMAGE_POSITIVE]
    exclusions = "、".join(negatives)
    statements.extend(positive for pattern, positive in _POSITIVE_EQUIVALENTS if pattern.search(exclusions))
    if video and re.search(r"杂音|爆音|audio noise|clipping", exclusions, re.I):
        statements.append("对白清晰，音量平稳。")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    pending = "\n".join(statement for statement in statements if statement not in body)
    return "\n\n".join(part for part in (body, pending) if part)
