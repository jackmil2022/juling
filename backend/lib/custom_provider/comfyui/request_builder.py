"""实发 workflow 的构造：在底稿深拷贝上按节点绑定填值、换算尺寸与帧数、定种子、按张数改图。

一次生成请求要变成一份 ComfyUI 能提交的 workflow，中间隔着四件换算：项目只给比例与分辨率档，
workflow 要的是像素；项目只给时长，workflow 要的是帧数；种子按绑定条目的策略或随机或保留；参考
图张数少于 workflow 预留的格子时得把多余的读图节点连同它们的下游一起删掉，而不是把最后一张
重复填满。四件都只依赖入参，不读配置、不碰数据库、不发请求——上传素材由调用方先做完，传进来的
是服务端已认得的引用名。

底稿一律不动：``definition["workflow"]`` 是这个端点的唯一真相，每次提交都从它深拷贝一份再填。
产出连同 ``workflow_sha256`` 一起回传，同一份入参两次构造得到同一个摘要，预览请求与真实提交据此
可比。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from random import Random
from typing import Any

from juling_market_core.aspect_size import (
    DEFAULT_SHORT_EDGE,
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    parse_aspect_ratio,
)
from juling_market_core.aspect_size import resolution_to_short_edge as short_edge_of_resolution
from juling_market_core.comfyui.bindings import align_frames, step_of
from juling_market_core.comfyui.bindings import bound_fps as _bound_fps
from juling_market_core.comfyui.bindings import int_literal_of as _int_literal
from juling_market_core.comfyui.bindings import literal_of as _literal
from juling_market_core.comfyui.bindings import positive_number as _positive_number
from juling_market_core.comfyui.bindings import targets_of as _targets
from juling_market_core.comfyui.graph import link_of
from juling_market_core.comfyui.workflow import is_link, node_inputs
from lib.prompts.minimax import format_h3_reference_slots, h3_boundary_instruction, h3_continuity_instruction, h3_reference_slot
from lib.prompts.prompt_utils import append_avoid_text, normalize_image_prompt, split_avoid_lines

from .audio_inputs import apply_reference_audio
from .capabilities import continuous_director_node, is_pika_ref2va, keeps_its_own_frame_count, size_is_fixed
from .failures import EXECUTION_ERROR, IMAGE_DROP_UNSUPPORTED, ComfyuiError
from .inference_rules import InferenceRules, MergeNode, load_inference_rules

logger = logging.getLogger(__name__)

#: 随机种子的取值区间上界（不含）：ComfyUI 各采样器的 seed 输入按 32 位无符号整数收。
SEED_UPPER_BOUND = 2**32

#: 种子条目缺省策略，与 schema 的 ``default`` 同值。
_DEFAULT_SEED_POLICY = "random"


@dataclass(frozen=True)
class MediaInputs:
    """本次生成实际带上的素材引用名：服务端上传响应给出的 ``subfolder/name``（无子目录只写
    ``name``），由调用方在上传后拼好。

    ``None`` 与空序列的区别是「这次没给」，与「这个端点不支持」无关——后者看的是绑定三态。
    """

    start_image: str | None = None
    end_image: str | None = None
    reference_images: Sequence[str] = ()
    reference_videos: Sequence[str] = ()
    reference_audio_files: Sequence[str] = ()
    previous_clip: tuple[str, int] | None = None  # Uploaded video and its frame count.
    next_clip: str | None = None
    keyframe_mode: bool = False
    previous_clip_has_audio: bool = False
    next_clip_has_audio: bool = False
    previous_clip_fps: float | None = None
    next_clip_fps: float | None = None
    next_clip_frames: int | None = None


@dataclass(frozen=True)
class BuiltWorkflow:
    """一次构造的产出：实发 workflow、它的摘要，以及三项换算的落地值。

    ``width`` / ``height`` / ``frames`` / ``seed`` 为 ``None`` 表示该维度没有绑定、值以 workflow
    字面值为准。端点测试的预览请求按这几项给出换算说明，``dropped_nodes`` 则说明这次改图删掉了
    哪些节点，故它们与 workflow 一并回传而不是只留在日志里。

    ``negative_prompt`` 是从正文里拆出的排除项文本本身，不是负向节点最终的值——后者还带着
    workflow 作者写在那里的字面值，没有可写的负向入口时排除项留在正文，此字段为空。
    """

    workflow: dict[str, Any]
    workflow_sha256: str
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    negative_prompt: str = ""
    dropped_nodes: tuple[str, ...] = ()
    seam_trim: tuple[int, int] = (0, 0)


def build_workflow(
    definition: Mapping[str, Any],
    *,
    prompt: str,
    aspect_ratio: str,
    resolution: str | None = None,
    duration_seconds: float | None = None,
    media: MediaInputs | None = None,
    seed: int | None = None,
    rng: Random | None = None,
    legacy_video_size: bool = False,
) -> BuiltWorkflow:
    """按一份 ComfyUI 端点定义与一次生成请求，构造实发 workflow。

    ``rng`` 是随机种子的注入点，生产默认用模块级 :class:`~random.Random`；``seed`` 是请求自带的
    种子（图像请求可指定），它顶掉随机但顶不掉 ``keep`` 策略——作者声明保留字面值时，请求里的种子
    不该悄悄改写这份 workflow 的既定行为。

    先改图后填值：删节点会改变图的形状，而填值只认节点 id 与字段名，在残缺的图上填值只会把值写进
    一个即将消失的节点里。
    """
    workflow = deepcopy(dict(definition["workflow"]))
    bindings: Mapping[str, Any] = definition.get("bindings") or {}
    media_type = "image" if definition.get("media_type") == "image" else "video"

    media = media or MediaInputs()
    director_id = continuous_director_node(definition)
    audio_dropped = apply_reference_audio(workflow, bindings, media.reference_audio_files)
    dropped = audio_dropped + _apply_media(workflow, bindings, media, load_inference_rules(media_type))
    for target in _targets(bindings.get("aspect_ratio")):
        value = target["values"].get(aspect_ratio)
        if value is None:
            raise ComfyuiError("comfyui_aspect_ratio_unmapped", aspect_ratio=aspect_ratio, node=target["node"])
        _write_one(workflow, target, value)

    prompt_targets = _targets(bindings.get("prompt"))
    avoid_text = ""
    if media_type == "image":
        body = normalize_image_prompt(prompt)
        for target in prompt_targets:
            node = workflow.get(str(target["node"]), {})
            meta = node.get("_meta")
            requirements = meta.get("juling_prompt_requirements") if isinstance(meta, Mapping) else None
            text = f"{body}\n\n{requirements}" if isinstance(requirements, str) and requirements else body
            _write_one(workflow, target, text)
    else:
        negative_targets = [
            target for target in _targets(bindings.get("negative_prompt")) if str(target["node"]) in workflow
        ]
        body, avoid_text = split_avoid_lines(prompt) if negative_targets else (prompt, "")
        if director_id is not None:
            body = format_h3_reference_slots(
                body, director=True, images=len(media.reference_images),
                videos=len(media.reference_videos), audios=len(media.reference_audio_files),
            )
        _write_all(workflow, prompt_targets, body)
        _write_negative_prompt(workflow, negative_targets, avoid_text)
    pika = director_id is not None and is_pika_ref2va(definition)
    # The legacy Director graph upscales its latent 2× before decoding.
    output_scale = 2 if director_id is not None and any(
        node.get("class_type") == "MinimaxH3LatentUpscalerNode2D" and node_inputs(node).get("mode.scale") == 2
        for node in workflow.values()
    ) else 1
    width, height = _write_size(
        workflow, bindings, aspect_ratio=aspect_ratio, resolution=resolution, media=media_type,
        output_scale=output_scale, prefer_resolution=pika and not legacy_video_size,
    )
    # 图自己写着片长、而这份片长凑不出一档原生时长时不动帧数：端点对外说的正是「时长不由
    # 剧灵 驱动」（档位为空、界面只读），请求里那个秒数是规划层借的，不是用户选的。
    seam_trim = (0, 0)
    if director_id is not None:
        director_dropped, seam_trim = _configure_director(
            workflow, bindings, director_id, media, duration_seconds, pika=pika
        )
        dropped += director_dropped
        frames = None
        if duration_seconds is not None and (fps := _bound_fps(workflow, bindings)) is not None:
            # Director's group length uses the H3 17k+5 frame grid.
            count = max(5, round(duration_seconds * fps))
            frames = count + (5 - count) % 17
            _mutable_inputs(workflow[director_id])["total_frames"] = frames
    else:
        driven = None if keeps_its_own_frame_count(definition) else duration_seconds
        frames = _write_frames(workflow, bindings, duration_seconds=driven)
        if duration_seconds is not None and (group := minimax_reference_duration_node(workflow, bindings)) is not None:
            _mutable_inputs(workflow[group])["duration_sec"] = float(duration_seconds)
    if any(seam_trim):
        dropped += _bypass_output_video_trims(workflow, bindings)
    elif duration_seconds is not None and (trim_node := output_video_trim(workflow, bindings)) is not None:
        trim = workflow[trim_node]
        if trim.get("class_type") == "VideoTemporalCrop":
            fps = _bound_fps(workflow, bindings)
            if fps is None:
                raise ComfyuiError(EXECUTION_ERROR, node=trim_node, detail="按帧裁剪需要绑定有效的输出帧率。")
            _mutable_inputs(trim)["length"] = max(1, round(duration_seconds * fps))
        else:
            _mutable_inputs(trim)["duration"] = float(duration_seconds)
    actual_seed = _write_seed(workflow, bindings, requested=seed, rng=rng or Random())

    return BuiltWorkflow(
        workflow=workflow,
        workflow_sha256=workflow_sha256(workflow),
        seed=actual_seed,
        width=width,
        height=height,
        frames=frames,
        negative_prompt=avoid_text,
        dropped_nodes=dropped,
        seam_trim=seam_trim,
    )


def workflow_sha256(workflow: Mapping[str, Any]) -> str:
    """一份 workflow 的内容摘要。

    按规范化 JSON（键排序、无多余空白、非 ASCII 原样）取 SHA-256：同一份内容不论 dict 的插入序
    如何都得到同一个摘要，预览请求与真实提交、两次构造之间才可比。
    """
    canonical = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 填值原语


def _mutable_inputs(node: Any) -> dict[str, Any]:
    """取一个节点可写的 ``inputs``。缺 ``inputs`` 或形状不对时就地补一个空表。"""
    if not isinstance(node, dict):
        return {}
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
        node["inputs"] = inputs
    return inputs


def _write_one(workflow: dict[str, Any], target: Mapping[str, Any], value: object) -> None:
    """把一个值写进一个目标。目标节点已在改图中消失时跳过，不新建节点。"""
    node_id = str(target["node"])
    name = target.get("input")
    if node_id not in workflow or not isinstance(name, str):
        logger.debug("跳过填值：节点 %s 的 %r 已不在实发 workflow 中", node_id, name)
        return
    _mutable_inputs(workflow[node_id])[name] = value


def _write_all(workflow: dict[str, Any], targets: Sequence[Mapping[str, Any]], value: object) -> None:
    """把同一个值写进一个语义键的全部目标。

    收 已规范化 的条目序列，不在内部再规范一次：调用方手里本就有 :func:`_targets` 的结果，函数
    再收一次原始值就会出现「传进来的到底是哪一种」的歧义——传规范化过的结果进来反而被判成形状
    不对而整批丢掉。
    """
    for target in targets:
        _write_one(workflow, target, value)


# ---------------------------------------------------------------- 负向提示词


def _write_negative_prompt(
    workflow: dict[str, Any], targets: Sequence[Mapping[str, Any]], avoid_text: str
) -> None:
    """把正文里拆出的排除项追加到负向节点的字面值之后。

    未绑定（空列表或键缺失）时什么也不填，正文里的 ``Avoid:`` 行原样随请求发送。
    """
    for target in targets:
        literal = _literal(workflow, target)
        _write_one(workflow, target, append_avoid_text(literal if isinstance(literal, str) else "", avoid_text))


# ---------------------------------------------------------------- 尺寸


def _write_size(
    workflow: dict[str, Any],
    bindings: Mapping[str, Any],
    *,
    aspect_ratio: str,
    resolution: str | None,
    media: str,
    output_scale: int = 1,
    prefer_resolution: bool = False,
) -> tuple[int | None, int | None]:
    """按项目比例与分辨率档派生宽高，逐条目按步长向下对齐后写入。

    ``round_to`` 取宽高两侧全部步长的最小公倍数。Pika 显式选择分辨率时优先贴近档位并独立对齐宽高，
    其他情况严格保证画幅比例。写入时仍按各绑定自己的步长校验尺寸。

    分辨率未选时短边取 workflow 字面宽高的较小者：这份 workflow 的原生尺寸就是作者调好的那一档，
    比例仍按项目走。字面值读不出整数时退到跨后端统一的兜底短边。

    尺寸这一维驱不驱动得了走 :func:`~lib.custom_provider.comfyui.capabilities.size_is_fixed` 这一份
    判据——界面据它禁用分辨率选择器，填值据它决定写不写，两处不各写一份。只绑一侧时它判为固定：
    派生出的宽高只写得进绑了的那一侧，另一侧仍是 workflow 的字面值，产出的比例既不是原生的也不是
    用户要的。
    """
    if size_is_fixed(bindings):
        return None, None
    width_targets = _targets(bindings.get("width"))
    height_targets = _targets(bindings.get("height"))

    round_to = math.lcm(*[_size_step(target) for target in (*width_targets, *height_targets)])
    tier_map = IMAGE_TIER_SHORT_EDGE if media == "image" else VIDEO_TIER_SHORT_EDGE
    requested = bool(resolution and resolution.strip())
    if requested:
        short_edge = short_edge_of_resolution(resolution, tier_map=tier_map) // output_scale
    else:
        short_edge = _literal_short_edge(workflow, width_targets, height_targets)

    if prefer_resolution and requested:
        # 独立对齐宽高，避免精确画幅的公倍数让相邻档位落到同一尺寸。
        ratio_width, ratio_height = parse_aspect_ratio(aspect_ratio)
        units = short_edge / (min(ratio_width, ratio_height) * round_to)
        width = round(ratio_width * units) * round_to
        height = round(ratio_height * units) * round_to
    else:
        width, height = aspect_size(aspect_ratio, short_edge, round_to=round_to)
    written_width = _write_stepped(workflow, width_targets, width)
    written_height = _write_stepped(workflow, height_targets, height)
    return (written_width * output_scale if written_width else None,
            written_height * output_scale if written_height else None)


def _literal_short_edge(
    workflow: Mapping[str, Any],
    width_targets: Sequence[Mapping[str, Any]],
    height_targets: Sequence[Mapping[str, Any]],
) -> int:
    literals = [
        value
        for target in (*width_targets, *height_targets)
        if (value := _int_literal(workflow, target)) is not None and value > 0
    ]
    if not literals:
        logger.info("分辨率未选且 workflow 字面宽高读不出整数，短边取兜底 %d", DEFAULT_SHORT_EDGE)
        return DEFAULT_SHORT_EDGE
    return min(literals)


def _write_stepped(workflow: dict[str, Any], targets: Sequence[Mapping[str, Any]], value: int) -> int | None:
    """把一个派生尺寸按各条目的步长向下对齐后写入，回传最后写出的值。"""
    written: int | None = None
    for target in targets:
        written = _align_down(value, _size_step(target))
        _write_one(workflow, target, written)
    return written


def _size_step(target: Mapping[str, Any]) -> int:
    step = step_of(target)
    if target.get("class_type") == "H3MultiRefConditioning":
        return math.lcm(step, 32)
    return step


def _align_down(value: int, step: int) -> int:
    """向下对齐到 ``step`` 的整数倍，下限一个 ``step``——零尺寸提交上去必然报错。"""
    return max(step, value - value % step)


# ---------------------------------------------------------------- 帧数


def _configure_director(
    workflow: dict[str, Any], bindings: Mapping[str, Any], node: str, media: MediaInputs, duration: float | None,
    *, pika: bool = False,
) -> tuple[tuple[str, ...], tuple[int, int]]:
    director = _mutable_inputs(workflow[node])
    reference_media = bool(media.reference_images or media.reference_videos or media.reference_audio_files)
    keyframes = bool(media.start_image or media.end_image or media.keyframe_mode)
    if pika:
        keyframes = not (reference_media or media.previous_clip or media.next_clip)
    if keyframes and reference_media:
        raise ComfyuiError(EXECUTION_ERROR, node=node, detail="H3 首尾帧和参考素材要分开提交。")
    active, inactive = ("i2v_groups", "r2v_groups") if keyframes else ("r2v_groups", "i2v_groups")
    group_link = _as_link(director.get(active))
    if group_link is None:
        raise ComfyuiError(EXECUTION_ERROR, node=node, detail=f"H3 Director 缺少 {active} 连线。")
    orphaned: set[str] = set()
    if unused := _as_link(director.pop(inactive, None)):
        orphaned.add(str(unused[0]))
    group = _mutable_inputs(workflow[str(group_link[0])])
    if duration is not None:
        group["duration_sec"] = float(duration)
    if pika and not keyframes:
        index = len(media.reference_images)
        for key, image in (
            ("start_image", media.start_image), ("end_image", media.end_image),
        ):
            if not image:
                continue
            target = _targets(bindings.get(key))
            if index >= 9 or len(target) != 1:
                raise ComfyuiError(EXECUTION_ERROR, node=node, detail="Pika boundary images require free reference slots.")
            group[f"ref_images.ref_image_{index}"] = [str(target[0]["node"]), 0]
            slot = h3_reference_slot("image", index + 1, director=True)
            group["prompt"] += "\n" + h3_boundary_instruction(slot, first=key == "start_image")
            index += 1
    if keyframes:
        # Pika's Ref2VA LoRA cannot drive native first/last-frame conditioning.
        fl2va = next((
            i for i, n in workflow.items()
            if n.get("class_type") == "UNETLoader" and "fl2va" in str(node_inputs(n).get("unet_name", "")).lower()
        ), None)
        if fl2va is None:
            raise ComfyuiError(EXECUTION_ERROR, node=node, detail="H3 首尾帧模式需要 FL2VA 底模。")
        for port in ("model", "sigmas"):
            if link := _as_link(director.pop(port, None)):
                orphaned.add(str(link[0]))
        task_type = "fl2v — 首尾帧生视频(First-Last Frame)"
        if pika and not media.end_image:
            task_type = "i2v — 图生视频(Image to Video)" if media.start_image else "t2v — 文生视频(Text to Video)"
        director.update(model=[fl2va, 0], task_type=task_type,
                        steps=20, sampler="euler", scheduler="simple", cfg=1.0)

    slots = iter(enumerate(_targets(bindings.get("reference_videos")), 1))
    for _ in media.reference_videos:
        next(slots, None)
    neighbor_frames = {}
    for side, filename, count, frame_port, has_audio, source_fps in (
        ("before", media.previous_clip[0] if media.previous_clip else None,
         media.previous_clip[1] if media.previous_clip else None, "first_frame",
         media.previous_clip_has_audio, media.previous_clip_fps),
        ("after", media.next_clip, media.next_clip_frames, "last_frame",
         media.next_clip_has_audio, media.next_clip_fps),
    ):
        if not filename:
            continue
        if keyframes:
            if frame_port in group:
                continue
            port, length = frame_port, 1
        else:
            slot = next(slots, None)
            if slot is None:
                neighbor = "上一镜" if side == "before" else "下一镜"
                raise ComfyuiError(EXECUTION_ERROR, node=node, detail=f"参考视频槽位不足，无法传入{neighbor}，请减少其他参考视频。")
            ordinal, target = slot
            port = target["consumer"]["input"]
            length = 22 if pika and side == "before" else 5
            if pika:
                length = min(count, length) if count is not None else length
                neighbor_frames[side] = length
            slot = h3_reference_slot("video", ordinal, director=True)
            group["prompt"] += "\n" + h3_continuity_instruction(slot, previous=side == "before", pika=pika)
        loader, split, batch = (f"juling_{side}_{suffix}" for suffix in ("video", "split", "frames"))
        if any(i in workflow for i in (loader, split, batch)):
            raise ComfyuiError(EXECUTION_ERROR, node=node, detail=f"H3 边界节点 ID 冲突：{side}。")
        workflow[loader] = {"class_type": "LoadVideo", "inputs": {"file": filename}}
        workflow[split] = {"class_type": "GetVideoComponents", "inputs": {"video": [loader, 0]}}
        workflow[batch] = {"class_type": "ImageFromBatch", "inputs": {
            "image": [split, 0], "batch_index": max(0, (count or 0) - length) if side == "before" else 0,
            "length": length,
        }}
        group[port] = [batch, 0]
        if pika and not keyframes and has_audio and port.startswith("ref_videos.ref_video_"):
            suffix = port.removeprefix("ref_videos.ref_video_")
            fps = source_fps or _bound_fps(workflow, bindings) or 24
            duration_seconds = length / fps
            trim = f"juling_{side}_audio"
            if trim in workflow:
                raise ComfyuiError(EXECUTION_ERROR, node=node, detail=f"H3 边界节点 ID 冲突：{side} audio。")
            workflow[trim] = {"class_type": "TrimAudioDuration", "inputs": {
                "audio": [split, 1],
                "start_index": -duration_seconds if side == "before" else 0.0,
                "duration": duration_seconds,
            }}
            group[f"ref_video_audios.ref_video_audio_{suffix}"] = [trim, 0]

    deleted: list[str] = []
    _prune_orphans(workflow, orphaned, pinned=_output_nodes(bindings), deleted=deleted)
    return tuple(deleted), (neighbor_frames.get("before", 0), neighbor_frames.get("after", 0))


_VIDEO_TRIM_NODES = {"Video Slice", "VideoTemporalCrop"}


def _bypass_output_video_trims(workflow: dict[str, Any], bindings: Mapping[str, Any]) -> tuple[str, ...]:
    """Save the full generated clip so local cuts start from its real frame count."""
    candidates: set[str] = set()
    for target in _targets(bindings.get("output")):
        output = workflow.get(str(target["node"]), {})
        if output.get("class_type") != "SaveVideo":
            continue
        inputs = _mutable_inputs(output)
        link = link_of(inputs.get("video"))
        visited: set[str] = set()
        while link is not None and link[1] == 0:
            node = workflow.get(link[0], {})
            if node.get("class_type") not in _VIDEO_TRIM_NODES:
                break
            if link[0] in visited:
                raise ComfyuiError(EXECUTION_ERROR, node=link[0], detail="产物裁剪节点连线成环。")
            visited.add(link[0])
            upstream = link_of(node_inputs(node).get("video"))
            if upstream is None or upstream[0] not in workflow:
                raise ComfyuiError(EXECUTION_ERROR, node=link[0], detail="产物裁剪节点缺少视频输入。")
            inputs["video"] = list(upstream)
            link = upstream
        candidates.update(visited)
    deleted: list[str] = []
    _prune_orphans(workflow, candidates, pinned=_output_nodes(bindings), deleted=deleted)
    return tuple(deleted)


def output_video_trim(workflow: Mapping[str, Any], bindings: Mapping[str, Any]) -> str | None:
    """Locate the workflow's final native video trim immediately before its bound output."""
    for target in _targets(bindings.get("output")):
        output = workflow.get(str(target["node"]), {})
        if output.get("class_type") != "SaveVideo":
            continue
        link = link_of(node_inputs(output).get("video"))
        if (link is not None and link[1] == 0
                and workflow.get(link[0], {}).get("class_type") in _VIDEO_TRIM_NODES):
            return link[0]
    return None


def minimax_reference_duration_node(workflow: Mapping[str, Any], bindings: Mapping[str, Any]) -> str | None:
    """Find the effective duration input for a bound MiniMax Director with one direct reference group."""
    for target in _targets(bindings.get("frames")):
        node = workflow.get(str(target["node"]), {})
        if target.get("input") != "total_frames" or node.get("class_type") != "MiniMaxH3Director":
            continue
        link = link_of(node_inputs(node).get("r2v_groups"))
        if link is None or link[1] != 0:
            continue
        group = workflow.get(link[0], {})
        if group.get("class_type") == "MiniMaxH3DirectorGroupReferenceToVideo" and _positive_number(
            node_inputs(group).get("duration_sec")
        ) is not None:
            # External groups derive their own frame count from duration_sec, overriding total_frames.
            return link[0]
    return None


def _write_frames(
    workflow: dict[str, Any], bindings: Mapping[str, Any], *, duration_seconds: float | None
) -> int | None:
    """按时长与帧率换算帧数并写入。

    ``frames = round(时长 × 帧率) + 1``：ComfyUI 的视频模型按「首帧 + 若干段间隔」计帧，24 帧
    每秒的 1 秒是 25 帧而不是 24。帧率优先取 ``fps`` 只读绑定读出的字面值——那是这份 workflow 真
    正在用的帧率；没有该绑定时取 ``frames`` 条目上手填的常量。两处都没有就不写：凭一个猜出来的
    帧率改帧数，比让 workflow 保持它自己的字面值更容易出片长不符。

    步长对帧数的含义是 ``frames ≡ 1 (mod step)``（4n+1 / 8n+1 这类），向下对齐、下限 ``1 + step``。

    ``duration_seconds`` 为 ``None`` 即「这一维不由本次请求驱动」，调用方在端点给不出档位时传的
    就是它：那种情形下 workflow 的字面帧数原样留着。
    """
    targets = _targets(bindings.get("frames"))
    if not targets or duration_seconds is None:
        return None

    bound_fps = _bound_fps(workflow, bindings)
    written: int | None = None
    for target in targets:
        fps = bound_fps if bound_fps is not None else _positive_number(target.get("fps"))
        if fps is None:
            logger.info("帧数未写：既无 fps 只读绑定，条目也未手填帧率")
            continue
        step = step_of(target)
        written = align_frames(round(duration_seconds * fps) + 1, step)
        _write_one(workflow, target, written)
    return written


# ---------------------------------------------------------------- 种子


def _write_seed(
    workflow: dict[str, Any], bindings: Mapping[str, Any], *, requested: int | None, rng: Random
) -> int | None:
    """按各条目的策略定种子并写入，回传本次实际生效的种子。

    ``random`` 条目写同一个值：一份 workflow 里的多个采样器（MoE 的双采样器是常见形态）共用一个
    种子，两个采样器各随机一次会让同一次生成不可复现。``keep`` 条目一个字节都不动，请求自带的
    种子也顶不掉它——作者声明保留字面值是这份 workflow 的既定行为。

    回传值是「实际生效的种子」而不是「生成的种子」：全是 ``keep`` 时回传字面值，版本元数据记下
    的才是重跑这一版真正要用的那个数。
    """
    targets = _targets(bindings.get("seed"))
    if not targets:
        return None
    rolling = [target for target in targets if target.get("policy", _DEFAULT_SEED_POLICY) == _DEFAULT_SEED_POLICY]
    if not rolling:
        return next((value for target in targets if (value := _int_literal(workflow, target)) is not None), None)

    value = requested if requested is not None else rng.randrange(SEED_UPPER_BOUND)
    for target in rolling:
        _write_one(workflow, target, value)
    return value


# ---------------------------------------------------------------- 改图


def _apply_media(
    workflow: dict[str, Any], bindings: Mapping[str, Any], media: MediaInputs, rules: InferenceRules
) -> tuple[str, ...]:
    """填入本次带上的素材，并把没有素材可填的读图节点连同下游一并删掉。

    首尾帧与参考图都是「绑定了但这次没给值」就要改图：读图节点留在图里会按 workflow 的字面
    文件名去读一张上次的图，模型照着它出片，用户看到的是一张自己没选过的首帧。
    """
    doomed: list[str] = []
    for key, value in (("start_image", media.start_image), ("end_image", media.end_image)):
        targets = _targets(bindings.get(key))
        if value is not None:
            _write_all(workflow, targets, value)
        else:
            doomed.extend(str(target["node"]) for target in targets)
    doomed.extend(
        _apply_reference_images(workflow, _targets(bindings.get("reference_images")), media.reference_images, rules)
    )
    doomed.extend(
        _apply_reference_media(
            workflow,
            _targets(bindings.get("reference_videos")),
            media.reference_videos,
            rules,
            label="参考视频",
        )
    )
    if not doomed:
        return ()
    return _drop_nodes(workflow, doomed, output_nodes=_output_nodes(bindings), rules=rules)


def _apply_reference_images(
    workflow: dict[str, Any],
    targets: Sequence[Mapping[str, Any]],
    values: Sequence[str],
    rules: InferenceRules,
) -> list[str]:
    """按张数填参考图，回传要删的读图节点。

    张数少于格子数时删多余的格子，而不是把最后一张重复填满——重复一张会让模型把它当成被强调了
    两次的主体。前提是认得这个格子接到的那个入口：``consumer`` 是保存绑定时记下的落点，它落在
    可选入口或两两合并节点上才改得动图。没记下 ``consumer``、或它落在这两张表之外，都算不认识
    ——此时退回重复最后一张，宁可构图偏了也不凭猜测把一个必需输入摘掉、让 ComfyUI 在提交时报
    ``node_errors``。保存这份绑定时推断已按同一条判据给过提示。一张都没给时连可重复的都没有，
    读图节点保持底稿字面值。
    """
    if len(targets) == 1:
        target = targets[0]
        if target.get("class_type") == "H3MultiRefPanel" and target.get("input") == "refs_json":
            _write_one(workflow, target, json.dumps(list(values), ensure_ascii=False))
            return []
    filled = min(len(targets), len(values))
    for index in range(filled):
        _write_one(workflow, targets[index], values[index])
    spare = targets[filled:]
    if not spare:
        return []
    if any(not _adjustable(target, rules) for target in spare):
        logger.info("参考图格子 %d 个、本次 %d 张，但有格子的 consumer 改不动图，改图跳过", len(targets), len(values))
        if values:
            _write_all(workflow, spare, values[-1])
        return []
    return [str(target["node"]) for target in spare]


def _apply_reference_media(
    workflow: dict[str, Any],
    targets: Sequence[Mapping[str, Any]],
    values: Sequence[str],
    rules: InferenceRules,
    *,
    label: str,
) -> list[str]:
    """按顺序填充视频等可选参考素材槽位；空槽位连同其音频下游一起删掉。"""
    filled = min(len(targets), len(values))
    for index in range(filled):
        _write_one(workflow, targets[index], values[index])
    spare = targets[filled:]
    if not spare:
        return []
    if any(not _adjustable(target, rules) for target in spare):
        logger.info("%s格子 %d 个、本次 %d 个，但 consumer 不可调整，保留最后一个引用", label, len(targets), len(values))
        if values:
            _write_all(workflow, spare, values[-1])
        return []
    return [str(target["node"]) for target in spare]


def _adjustable(target: Mapping[str, Any], rules: InferenceRules) -> bool:
    """这个参考图格子在张数变少时改得动图吗。"""
    consumer = target.get("consumer")
    if not isinstance(consumer, Mapping):
        return False
    class_type = consumer.get("class_type")
    input_name = consumer.get("input")
    if not isinstance(class_type, str) or not isinstance(input_name, str):
        return False
    return rules.adjustable_input(class_type, input_name)


def _output_nodes(bindings: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(str(target["node"]) for target in _targets(bindings.get("output")))


def _drop_nodes(
    workflow: dict[str, Any], seeds: Sequence[str], *, output_nodes: frozenset[str], rules: InferenceRules
) -> tuple[str, ...]:
    """删掉给定的节点，前向级联到下游、后向清理只喂给它们的上游。

    前向三种处置按节点类型分（判据在推断规则表的可选入口与合并节点两节）：允许缺席的输入摘键、
    两两合并节点 bypass、其余连它一起删并继续级联。级联触到产物节点即失败：成片链路本身依赖这张
    图，提交一份缺了它的 workflow 只会换来一次远端报错加一次等待。
    """
    deleted: list[str] = []
    orphan_candidates: set[str] = set()
    pending = list(seeds)
    while pending:
        node_id = pending.pop()
        if node_id not in workflow:
            continue
        if node_id in output_nodes:
            raise ComfyuiError(IMAGE_DROP_UNSUPPORTED, node=node_id)
        orphan_candidates.update(_link_sources(workflow[node_id]))
        del workflow[node_id]
        deleted.append(node_id)
        pending.extend(_detach_consumers(workflow, node_id, output_nodes, deleted, orphan_candidates, rules))
    _prune_orphans(workflow, orphan_candidates, pinned=output_nodes, deleted=deleted)
    return tuple(deleted)


def _detach_consumers(
    workflow: dict[str, Any],
    node_id: str,
    output_nodes: frozenset[str],
    deleted: list[str],
    orphan_candidates: set[str],
    rules: InferenceRules,
) -> list[str]:
    """处置引用了刚删掉那个节点的全部下游，回传其中必须一并删除的。"""
    doomed: list[str] = []
    for consumer_id in list(workflow):
        consumer = workflow.get(consumer_id)
        if consumer is None:
            continue
        inputs = _mutable_inputs(consumer)
        names = [name for name, raw in inputs.items() if _refers_to(raw, node_id)]
        if not names:
            continue
        class_type = str(consumer.get("class_type") or "")
        merge = rules.merge_node(class_type)
        for name in names:
            if rules.is_optional_input(class_type, name):
                del inputs[name]
            elif merge is not None and name in merge.inputs and consumer_id not in output_nodes:
                if _bypass_merge(workflow, consumer_id, merge, name, deleted, orphan_candidates):
                    break
                doomed.append(consumer_id)
            else:
                doomed.append(consumer_id)
    return doomed


def _bypass_merge(
    workflow: dict[str, Any],
    merge_id: str,
    merge: MergeNode,
    dropped: str,
    deleted: list[str],
    orphan_candidates: set[str],
) -> bool:
    """把一个两两合并节点从图里摘掉，它的下游改接剩下那一路。

    剩下那一路必须是条还连着活节点的连线才摘得掉。两种情况摘不掉，都只能把这个节点也删掉、继续
    级联：换成字面值就没有「上游」可以改接；两个入口接的是同一个读图节点时，「剩下那一路」指的
    正是刚刚删掉的那个节点，照它改接只会给下游留一条悬空连线，而这份 workflow 照样会提交出去。

    不新增节点，只改下游的引用。
    """
    inputs = _mutable_inputs(workflow[merge_id])
    first, second = merge.inputs
    survivor = _as_link(inputs.get(second if dropped == first else first))
    if survivor is None or str(survivor[0]) not in workflow:
        return False
    for other_id in list(workflow):
        if other_id == merge_id:
            continue
        other_inputs = _mutable_inputs(workflow[other_id])
        for name, raw in list(other_inputs.items()):
            if _refers_to(raw, merge_id):
                other_inputs[name] = list(survivor)
    orphan_candidates.update(_link_sources(workflow[merge_id]))
    del workflow[merge_id]
    deleted.append(merge_id)
    return True


def _prune_orphans(
    workflow: dict[str, Any], candidates: set[str], *, pinned: frozenset[str], deleted: list[str]
) -> None:
    """后向清理：只喂给已删节点的上游随之删除。

    候选只来自被删节点的连线上游，不是「图里所有没有下游的节点」——预览节点之类本来就没有下游，
    一并扫掉等于替用户改写这份 workflow。承载绑定的节点不额外留下：下游全没了之后它已是死节点，
    往里填的值 ComfyUI 也不会执行到。
    """
    pending = set(candidates)
    while pending:
        node_id = pending.pop()
        if node_id not in workflow or node_id in pinned or _has_consumer(workflow, node_id):
            continue
        pending.update(_link_sources(workflow[node_id]))
        del workflow[node_id]
        deleted.append(node_id)


def _has_consumer(workflow: Mapping[str, Any], node_id: str) -> bool:
    return any(
        _refers_to(raw, node_id)
        for other_id, other in workflow.items()
        if other_id != node_id
        for raw in node_inputs(other).values()
    )


def _as_link(raw: object) -> list[Any] | None:
    """该字段是一条连线时回传它本身，否则 ``None``。字面数组的包装形态不算连线。"""
    return raw if isinstance(raw, list) and is_link(raw) else None


def _refers_to(raw: object, node_id: str) -> bool:
    """该字段是否是一条指向 ``node_id`` 的连线。"""
    link = _as_link(raw)
    return link is not None and str(link[0]) == node_id


def _link_sources(node: Any) -> set[str]:
    """一个节点全部连线输入的上游节点 id。"""
    return {str(link[0]) for raw in node_inputs(node).values() if (link := _as_link(raw)) is not None}
