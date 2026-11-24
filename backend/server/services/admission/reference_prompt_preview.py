"""参考生视频单元的最终提示词，使用当前请求投影的实发参考图与能力。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from lib.artifacts.artifact_currency import active_artifact_currency_resolver
from lib.artifacts.artifact_input_claims import resolve_continuity_video_inputs, resolve_h3_reference_video_inputs
from lib.generation.batch_admission import DURATION_CONFIRMATION_CODE
from lib.generation.video_request_facts import VideoRequestFacts
from lib.i18n import render_message
from lib.i18n.display_names import DisplayNames
from lib.prompts.minimax import (
    format_h3_reference_slots,
    h3_boundary_instruction,
    h3_continuity_instruction,
    h3_reference_slot,
    is_minimax_h3_video,
)
from lib.script.reference_video.prompt_render import render_video_unit_prompt, resolve_reference_audio_paths
from lib.script.reference_video.request_projection import NARRATOR_AUDIO_REQUIRED, ReferenceUnitRequestProjection
from lib.script.reference_video.voice_settings import VoiceRenderSettings


def format_video_preview_media(
    text: str, references: list[dict[str, str]], facts: VideoRequestFacts,
) -> str:
    """Label actual attachments by type and add the same Director boundary instructions as the workflow."""
    if not (facts.h3_director or is_minimax_h3_video(facts.model_id)):
        return text
    counts = dict.fromkeys(("image", "video", "audio"), 0)
    for reference in references:
        if "role" not in reference:
            kind = reference["kind"]
            counts[kind] += 1
            reference["slot"] = h3_reference_slot(kind, counts[kind], director=facts.h3_director)
    if not facts.h3_director:
        return text

    text = format_h3_reference_slots(text, director=True, images=counts["image"], videos=counts["video"], audios=counts["audio"])
    has_frames = any(ref.get("role") in {"first_frame", "last_frame"} for ref in references)
    has_neighbors = any(ref.get("role") in {"previous_video", "next_video"} for ref in references)
    pika_reference_mode = facts.h3_pika and (has_neighbors or any(counts.values()))
    boundary_lines = []
    for ref in references:
        role = ref.get("role")
        if role in {"first_frame", "last_frame"} and pika_reference_mode:
            counts["image"] += 1
            ref["slot"] = h3_reference_slot("image", counts["image"], director=True)
            boundary_lines.append(h3_boundary_instruction(ref["slot"], first=role == "first_frame"))
        elif role in {"previous_video", "next_video"} and (not has_frames or pika_reference_mode):
            counts["video"] += 1
            ref["slot"] = h3_reference_slot("video", counts["video"], director=True)
            boundary_lines.append(h3_continuity_instruction(ref["slot"], previous=role == "previous_video", pika=facts.h3_pika))
    return "\n".join((text, *boundary_lines))


def continuity_preview_media(
    project_path: Path, project: dict, episode: int, items: list, id_field: str, item_id: str,
    *, storyboard: bool = False, first_frame: bool = False, last_frame: bool = False,
) -> list[dict[str, str]]:
    inputs = resolve_continuity_video_inputs(
        project_path, active_artifact_currency_resolver(project_path, project), episode,
        items, id_field, item_id, storyboard=storyboard, require_previous=False,
    )
    return [
        {"kind": "video", "role": role, "name": str(claim.key.components[-1]),
         "path": path.relative_to(project_path).as_posix()}
        for role, (path, claim) in inputs.items()
        if not (role == "previous_video" and first_frame or role == "next_video" and last_frame)
    ]


def reference_prompt_preview_facts(
    *,
    project: dict,
    unit: dict,
    script: dict,
    episode: int,
    project_path: Path,
    projection: ReferenceUnitRequestProjection,
) -> dict[str, Any]:
    """只读渲染；时长待确认不妨碍查看文本，其他投影阻断项显式显示为不可用。

    与分镜预览同一口径：``text`` 与 ``unavailable`` 恰有一个非 ``None``，``warnings`` 只随文本出现。
    """
    result: dict[str, Any] = {
        "text": None,
        "editable_text": None,
        "unavailable": None,
        "unavailable_params": {},
        "is_text_form": True,
        "references": [],
        "narrator_reference_missing": any(problem.code == NARRATOR_AUDIO_REQUIRED for problem in projection.problems),
        "warnings": [],
    }
    blockers = [problem for problem in projection.blocking_problems
                if problem.code not in {DURATION_CONFIRMATION_CODE, NARRATOR_AUDIO_REQUIRED}]
    if blockers:
        result["unavailable"] = blockers[0].code
        result["unavailable_params"] = blockers[0].parameters()
        return result
    request_facts = projection.request_facts
    if request_facts is None:
        result["unavailable"] = "reference_capability_unavailable"
        result["unavailable_params"] = {"capability": projection.hydrated_generation_type}
        return result
    if not str(unit.get("text") or "").strip():
        result["unavailable"] = "reference_prompt_preview_missing"
        return result

    project_path = project_path.resolve()
    try:
        clips = resolve_h3_reference_video_inputs(
            project_path, project, episode, script, unit, request_facts.model_id, h3_director=request_facts.h3_director,
        )
        neighbors = continuity_preview_media(
            project_path, project, episode, script.get("video_units") or [], "unit_id", str(unit.get("unit_id")),
        ) if request_facts.h3_director else []
    except ValueError as exc:
        result["unavailable"] = "reference_prompt_preview_video_unavailable"
        result["unavailable_params"] = {"detail": str(exc)}
        return result
    audio_paths = resolve_reference_audio_paths(project, project_path)
    voice_settings = VoiceRenderSettings.from_request_facts(request_facts, audio_ready=audio_paths)
    rendered = render_video_unit_prompt(
        unit,
        project,
        voice_settings,
        request_references=[asset.reference for asset in projection.request_assets],
        model=request_facts.model_id,
        h3_director=request_facts.h3_director,
    )
    result["references"] = [
        {
            "kind": "image",
            "type": asset.reference.type,
            "name": asset.reference.name,
            "path": asset.path.relative_to(project_path).as_posix(),
        }
        for asset in projection.request_assets
    ]
    result["references"].extend(
        {"kind": "video", "name": name, "path": path.relative_to(project_path).as_posix()}
        for name, path, _ in clips
    )
    result["references"].extend(
        {"kind": "audio", "name": speaker, "path": audio_paths[speaker].relative_to(project_path).as_posix()}
        for speaker in rendered.audio_speakers
    )
    result["references"].extend(neighbors)
    result["text"] = format_video_preview_media(rendered.prompt, result["references"], request_facts)
    editable = render_video_unit_prompt(
        unit,
        project,
        voice_settings,
        request_references=[asset.reference for asset in projection.request_assets],
        model=request_facts.model_id,
        h3_director=request_facts.h3_director,
        preserve_mentions=True,
    )
    result["editable_text"] = editable.prompt
    result["warnings"] = [
        *({"key": problem.code, "params": problem.parameters()} for problem in projection.problems),
        *rendered.warnings,
    ]
    return result


def render_reference_prompt_preview(
    *,
    project: dict,
    unit: dict,
    script: dict,
    episode: int,
    project_path: Path,
    projection: ReferenceUnitRequestProjection,
    translate: Callable[..., str],
    names: DisplayNames,
) -> dict[str, Any]:
    """将共享预览的原因码与警告渲染为 Web 文案。"""
    result = reference_prompt_preview_facts(
        project=project,
        unit=unit,
        script=script,
        episode=episode,
        project_path=project_path,
        projection=projection,
    )
    params = result.pop("unavailable_params")
    if result["unavailable"] is not None:
        result["unavailable"] = render_message(result["unavailable"], params, translate, names)
    result["warnings"] = [
        render_message(warning["key"], warning["params"], translate, names) for warning in result["warnings"]
    ]
    return result
