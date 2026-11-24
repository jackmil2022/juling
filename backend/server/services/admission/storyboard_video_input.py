"""Project the actual duration, prompt and ordered media of a storyboard request."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.artifacts.artifact_currency import active_artifact_currency_resolver
from lib.artifacts.artifact_input_claims import resolve_continuity_video_inputs
from lib.artifacts.artifact_manifest import ArtifactInputClaim
from lib.artifacts.generation_input import (
    AssembledReference, InputObservation, InputRefused, resolve_storyboard_shot_images, select_storyboard_video_images,
    storyboard_shots, storyboard_video_reference_id, storyboard_video_references,
)
from lib.generation.video_request_facts import VideoRequestFacts
from lib.infra.api_errors import BadRequestError
from lib.project.asset_types import NARRATOR_CHARACTER, asset_name_comparison_key, is_audio_only_character
from lib.prompts.minimax import format_h3_reference_slots, h3_continuity_instruction, h3_reference_slot, is_minimax_h3_video
from lib.prompts.prompt_utils import render_storyboard_video_prompt
from lib.references.reference_admission import UNREGISTERED_REFERENCE_CODE
from lib.script.reference_video.duration_slots import (
    VIDEO_MAX_SECONDS, VIDEO_MIN_SECONDS, VIDEO_REFERENCE_SLOTS,
    resolve_duration_slot, storyboard_duration_tiers, storyboard_planned_seconds,
)
from lib.script.reference_video.prompt_render import resolve_reference_audio_paths
from lib.script.reference_video.text_parser import UNIT_TIME_RANGE, pad_video_timeline
from lib.script.storyboard_sequence import continuous_neighbors, storyboard_needs_asset_images
from lib.speech.speech_composition import SpeechOwner, admit_script_unit
from lib.speech.speech_rate import storyboard_speech_seconds
from server.services.admission.reference_admission import input_refusal_error


@dataclass(frozen=True)
class StoryboardVideoInput:
    prompt: str
    duration: int
    tiers: tuple[int, ...]
    images: tuple[AssembledReference, ...]
    audio: dict[str, Path]
    audio_targets: tuple[int, ...] | None
    neighbors: dict[str, tuple[Path, ArtifactInputClaim]]
    preview: tuple[dict[str, str], ...]
    preview_prompt: str
    blockers: tuple[BadRequestError, ...]
    storyboard_images: dict[str, str]
    narrator_reference_missing: bool
    reference_blocker: BadRequestError | None
    required_previous_id: str | None

    def require(self) -> "StoryboardVideoInput":
        if self.blockers:
            error = self.blockers[0]
            if repair := error.params.get("repair"):
                error.with_diagnostic({"repair": repair})
            raise error
        return self


def project_storyboard_video_input(
    project: dict[str, Any], item: dict[str, Any], project_path: Path, observation: InputObservation,
    facts: VideoRequestFacts | None, *, content_mode: str, skeleton_kind: str, episode: int,
    items: Sequence[Any], id_field: str, defer_continuity: bool = False,
    planned_neighbors: Mapping[str, str] | None = None,
    prompt: object = None, fallback_duration: object = None,
) -> StoryboardVideoInput:
    resource_id = str(item[id_field])
    director = bool(facts and facts.h3_director)
    cloud_h3 = bool(facts and not director and is_minimax_h3_video(facts.model_id))
    continuity = bool(facts and (cloud_h3 or director or facts.bidirectional_video_continuity))
    raw_prompt = item.get("video_prompt") if prompt is None else prompt
    problems: list[BadRequestError] = []
    tiers = storyboard_duration_tiers(facts.allowed_durations if facts else range(VIDEO_MIN_SECONDS, VIDEO_MAX_SECONDS + 1))
    if not tiers and facts and facts.duration_endpoint_fixed and not facts.supported_durations:
        problems.append(BadRequestError("storyboard_video_duration_unknown", id=resource_id))
    try:
        planned = storyboard_planned_seconds(item.get("duration_seconds") or fallback_duration or project.get("default_duration") or 8)
    except (ValueError, OverflowError):
        raise BadRequestError("storyboard_video_duration_invalid", id=resource_id) from None
    duration = resolve_duration_slot(planned, tiers).seconds if tiers else max(VIDEO_MIN_SECONDS, min(VIDEO_MAX_SECONDS, int(planned)))
    if planned > duration or not tiers:
        problems.append(BadRequestError("storyboard_video_duration_exceeded", id=resource_id, planned=planned,
                                        limit=max(tiers, default=0), repair="split_storyboard"))
    assets, gaps = storyboard_video_references(project, item, observation, require_scene=False)
    try:
        shots = storyboard_shots(project, {**item, "video_prompt": raw_prompt}, assets, episode=episode, resource_id=resource_id)
    except ValueError as exc:
        raise BadRequestError("storyboard_video_timeline_invalid", id=resource_id) from exc
    neighbors = {}
    before, after = continuous_neighbors(items, id_field, resource_id)
    shot_images = resolve_storyboard_shot_images(
        shots, item, observation, episode=episode, resource_id=resource_id, assets_complete=not gaps,
    )
    preview_images = select_storyboard_video_images(
        item, use_asset_images=storyboard_needs_asset_images(before, item), assets=assets, shot_images=shot_images,
    )
    images = tuple(ref for ref, _ in preview_images)
    fusion_slots = {label: i for i, (_, label) in enumerate(preview_images, 1) if label is not None}
    required_previous_id = None
    if not images:
        # The immediate predecessor is required even at a scene change.
        after = None
        required_previous_id = str(before[id_field]) if before is not None else None
        if planned_neighbors is None:
            planned_neighbors = {"previous_video": required_previous_id} if required_previous_id is not None else {}
    if continuity and (before is not None or after is not None or planned_neighbors):
        resolver = active_artifact_currency_resolver(project_path, project)
        neighbors = resolve_continuity_video_inputs(
            project_path, resolver, episode, items, id_field, resource_id, planned=planned_neighbors,
            storyboard=bool(images), require_previous=False,
        )
    if planned_neighbors and not defer_continuity:
        for role, neighbor_id in planned_neighbors.items():
            if role not in neighbors and (images or role != "previous_video"):
                problems.append(BadRequestError("storyboard_video_neighbor_unavailable", id=resource_id, neighbor=neighbor_id))
    reference_blocker = None
    reserved_neighbor = False
    if not images and "previous_video" not in neighbors:
        if continuity and required_previous_id is not None:
            reference_blocker = BadRequestError("storyboard_video_previous_required", id=resource_id, previous=required_previous_id)
            reserved_neighbor = defer_continuity
        elif facts and before is not None:
            reference_blocker = BadRequestError("storyboard_video_continuity_unsupported", id=resource_id)
        else:
            reference_blocker = BadRequestError("video_reference_images_required", id=resource_id, model=facts.model_id if facts else "")
        if not reserved_neighbor:
            problems.append(reference_blocker)

    audio: dict[str, Path] = {}
    missing_speakers = []
    speakers: dict[str, str] = {}
    narrators: set[str] = set()
    spoken_seconds = 0.0
    if facts and facts.requested_generate_audio:
        utterances = admit_script_unit(skeleton_kind, item).preparation.utterances
        spoken_seconds = storyboard_speech_seconds((utterance.text for utterance in utterances), project)
        for utterance in utterances:
            is_narrator = utterance.owner is SpeechOwner.NARRATOR or bool(
                utterance.speaker and is_audio_only_character(utterance.speaker)
            )
            name = NARRATOR_CHARACTER if is_narrator else utterance.speaker
            if name:
                key = asset_name_comparison_key(name)
                speakers.setdefault(key, name)
                if is_narrator:
                    narrators.add(key)
    available = resolve_reference_audio_paths(project, project_path) if speakers else {}
    for key, name in speakers.items():
        if key in available:
            audio[key] = available[key]
        else:
            missing_speakers.append(name)
    if missing_speakers:
        problems.append(BadRequestError("storyboard_video_voice_required", id=resource_id, speakers="、".join(missing_speakers)))

    video_count = len(neighbors) + reserved_neighbor
    image_limit = facts.max_reference_images if facts and facts.max_reference_images is not None else VIDEO_REFERENCE_SLOTS
    audio_limit = facts.max_reference_audio_count if facts and facts.max_reference_audio_count is not None else VIDEO_REFERENCE_SLOTS
    slot_images = min(image_limit, VIDEO_REFERENCE_SLOTS - len(speakers) - video_count)
    asset_slots = [(ref.visual.logical_type, ref.visual.logical_id) for ref in images] if not fusion_slots else []
    # Director can allocate up to two additional internal neighbor slots. Inspect its actual partition below.
    def render() -> str:
        model = "MiniMax-H3" if director else facts.model_id if facts else ""
        body = render_storyboard_video_prompt(
            raw_prompt, {**item, "duration_seconds": planned}, content_mode=content_mode,
            voice_characters=project.get("characters") if speakers and not audio else None, model=model,
            references=asset_slots,
        )
        end = max((float(match[2]) for match in UNIT_TIME_RANGE.finditer(body)), default=0)
        if end > planned:
            raise BadRequestError("storyboard_video_timeline_exceeded", id=resource_id, planned=planned, end=end)
        if not end:
            body = f"[0s-{planned:g}s]\n{body}"
            end = planned
        if spoken_seconds > end:
            problems.insert(0, BadRequestError("storyboard_video_speech_overflow", id=resource_id,
                                               needed=f"{spoken_seconds:.1f}", available=end))

        def bind(match):
            shot = shots_by_start.get(float(match[1]))
            if shot is not None and (index := fusion_slots.get(shot.label)) is not None:
                return f"{match[0]}\n{slot('image', index)} 是 {shot.label} 的融合参考图，保持人物、场景和物品的比例与位置。"
            return match[0]

        shots_by_start = {shot.start: shot for shot in shots}
        return pad_video_timeline(UNIT_TIME_RANGE.sub(bind, body) if fusion_slots else body, end, duration)

    def slot(kind: str, index: int) -> str:
        prefix = "参考" if kind == "image" and not director else ""
        return prefix + h3_reference_slot(kind, index, director=director)

    body = render()
    clip_count = 1
    if director and tiers and planned <= duration:
        from lib.custom_provider.comfyui.continuous_video import plan_clips

        clips = plan_clips(body, duration, allow_unsplit=True)
        clip_count = len(clips)
        if clip_count > 1:
            internal_peak = max(
                int(index > 0 or "previous_video" in neighbors or reserved_neighbor)
                + int((index % 3 == 2) if index < len(clips) - 1 else "next_video" in neighbors)
                for index in range(len(clips))
            )
            slot_images = min(slot_images, VIDEO_REFERENCE_SLOTS - len(speakers) - internal_peak)

    if len(images) > slot_images or len(speakers) > audio_limit:
        repair = "fuse_storyboard_references" if not fusion_slots and 0 < len(shots) <= slot_images and len(speakers) <= audio_limit else "split_storyboard"
        problems.append(BadRequestError(
            "storyboard_video_slots_exceeded", id=resource_id, images=len(images), audios=len(speakers),
            videos=video_count, limit=VIDEO_REFERENCE_SLOTS, image_limit=max(0, slot_images), audio_limit=audio_limit,
            duration=duration, repair=repair,
        ))
    missing_references = tuple(gap for gap in gaps if gap.code == UNREGISTERED_REFERENCE_CODE)
    if missing_references:
        problems.append(input_refusal_error(InputRefused(missing_references)))

    targets = None
    if audio and facts and facts.reference_audio_per_image:
        problems.append(BadRequestError("storyboard_video_voice_target", id=resource_id))

    preview = [{"kind": "image", "name": f"{time_range} 参考图" if time_range else ref.visual.logical_id,
                "path": ref.artifact_path, "slot": slot("image", i),
                "reference_id": storyboard_video_reference_id(ref, time_range),
                **({"time_range": time_range} if time_range else {})}
               for i, (ref, time_range) in enumerate(preview_images, 1)]
    instructions = []
    for i, (role, (_, claim)) in enumerate(neighbors.items(), 1):
        previous = role == "previous_video"
        neighbor = before if previous else after
        assert neighbor is not None
        ordinal = i
        if director and clip_count > 1:
            ordinal = 1 if previous else 1 + int((clip_count - 1) % 3 != 0)
        label = slot("video", ordinal)
        preview.append({"kind": "video", "name": str(neighbor[id_field]), "path": claim.artifact_path, "slot": label, "role": role})
        instruction = h3_continuity_instruction(label, previous=previous, pika=bool(facts and facts.h3_pika))
        if director and clip_count > 1:
            instruction = ("首段：" if previous else "末段：") + instruction
        instructions.append(instruction)
    voices = ["按标注时间用自然语速逐字说完旁白或台词，保留完整句尾和停顿。"] if spoken_seconds else []
    for i, (key, path) in enumerate(audio.items(), 1):
        label = slot("audio", i)
        preview.append({"kind": "audio", "name": speakers[key], "path": path.relative_to(project_path).as_posix(), "slot": label})
        voice = f"角色「{speakers[key]}」的台词" if key not in narrators else "画外旁白（Voiceover）"
        voices.append(f"{label}仅用于{voice}的音色、口音和说话节奏；逐字读正文，不要复读参考音频。")
    if cloud_h3 or director:
        body = format_h3_reference_slots(body, director=director, images=len(images), videos=len(neighbors), audios=len(audio))
    prompt_text = "\n\n".join(part for part in ("\n".join(voices), body, "\n".join(instructions) if not director else "") if part)
    preview_prompt = f"{prompt_text}\n\n" + "\n".join(instructions) if director and instructions else prompt_text
    return StoryboardVideoInput(prompt_text, duration, tiers, images, audio, targets, neighbors, tuple(preview),
                                preview_prompt, tuple(problems),
                                {shot.label: ref.artifact_path for shot, ref in shot_images if ref is not None},
                                bool(narrators.difference(audio)), reference_blocker, required_previous_id)
