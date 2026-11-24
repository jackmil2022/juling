"""Editing Skill adapters scoped to an 剧灵 revision and its local media."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lib.edit_timeline import EditTimelineError, EditTimelineService
from lib.edit_timeline.model import ClipGrade
from lib.final_cut.errors import FinalCutError
from lib.final_cut.service import FinalCutService
from lib.infra.ffmpeg import FfmpegUnavailableError
from lib.infra.media_probe import MediaProbeError
from lib.video_review.contact_sheet import ContactSheetError, build_seam_contact_sheet
from server.agent_toolset.declaration import BLOCKED, ToolDeclaration, ToolImage
from server.agent_toolset.editing_skills_runtime import ROOT, EditingSkillError, run_skill, stage_window
from server.agent_toolset.timeline_seam import audio_levels, seam_context, source_bounds
from server.media_tools.context import tool_problem
from server.services.presentation.timeline_units import TimelineUnitMaterials
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline: str = Field(min_length=1)
    revision: int = Field(ge=1)


class ClipMediaRequest(RevisionRequest):
    clip: str = Field(min_length=1)


class PreviewGradeRequest(ClipMediaRequest):
    grade: ClipGrade
    edge: Literal["head", "tail"] = "head"


class SpeechRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _positive_length(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class DuckBgmRequest(RevisionRequest):
    regions: tuple[SpeechRegion, ...] | None = Field(default=None, max_length=300)
    depth_db: float = Field(default=10, gt=0, le=24)


class ReviewCutRequest(RevisionRequest):
    left_clips: tuple[str, ...] = Field(min_length=1, max_length=4)


def _error(exc):
    return tool_problem(str(exc), code=getattr(exc, "code", "editing_skill_failed"))


_SKILL_ERRORS = (EditingSkillError, EditTimelineError, FinalCutError, FfmpegUnavailableError,
                 ContactSheetError, MediaProbeError, OSError)


async def _clip_source(request, scope, services):
    read, clips, snapshots = await seam_context(scope.project_name, request.timeline, services)
    if read.revision != request.revision:
        raise EditTimelineError("revision_conflict", "时间线已更新，请按最新修订重试。")
    clip = next((clip for clip in clips if clip.id == request.clip), None)
    if clip is None or (snapshot := snapshots.get((clip.unit_id, clip.video_version))) is None:
        raise EditingSkillError("该片段没有可用的视频版本快照。")
    return clip, snapshot[0]


def _final_cut_service(services):
    return FinalCutService(services.projects, unit_materials=TimelineUnitMaterials(services.projects))


async def analyze_clip_media(
    request: ToolRequest[ClipMediaRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    try:
        clip, source = await _clip_source(value, scope, services)
        start, end = source_bounds(clip)
        with TemporaryDirectory(prefix="juling-edit-") as directory:
            workspace = Path(directory)
            staged = workspace / "clip.mp4"
            await stage_window(source, staged, start, end)
            checkout = "media-analysis-skill"
            args = ["-m", "media_analysis.cli", "analyze", str(staged), "--json", "--workspace", str(workspace),
                    "--allowed-input", str(workspace), "--timeout", "35"]
            evidence = await run_skill(checkout, [*args, "--kind", "timing", "--kind", "picture_quality"],
                                       workspace, python_root=ROOT / checkout / "src")
            try:
                audio = await run_skill(checkout, [*args, "--kind", "noise_floor", "--kind", "silence"],
                                        workspace, python_root=ROOT / checkout / "src")
            except EditingSkillError as exc:
                audio = {"status": "failed", "detail": str(exc)}
        return ToolOutcome(value={"revision": value.revision, "clip": clip.id, "version": clip.video_version,
                                  "source_in_seconds": start, "picture_and_timing": evidence, "audio": audio})
    except _SKILL_ERRORS as exc:
        return _error(exc)


async def preview_clip_grade(
    request: ToolRequest[PreviewGradeRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    try:
        clip, source = await _clip_source(value, scope, services)
        start, end = source_bounds(clip)
        before = value.edge == "tail"
        start, end = (max(start, end - 1), end) if before else (start, min(end, start + 1))
        with TemporaryDirectory(prefix="juling-edit-") as directory:
            workspace = Path(directory)
            staged, corrected = workspace / "clip.mp4", workspace / "grade.mp4"
            await stage_window(source, staged, start, end)
            spec = {
                "schema": "color-grading/request@1",
                "project": {
                    "project_id": "juling-preview", "source": {"source_id": "clip", "path": str(staged)},
                    "operations": [{"op_id": "grade", "type": "PRIMARY_CORRECTION", "input": "source",
                                    "parameters": {"exposure": value.grade.exposure, "temperature": value.grade.temperature, "preset": "ultrafast"}}],
                    "outputs": [{"output_id": "preview", "operation": "op:grade", "path": str(corrected), "format": "mp4"}],
                },
            }
            manifest = workspace / "request.json"
            manifest.write_text(json.dumps(spec), encoding="utf-8")
            checkout = "color-grading-skill"
            result = await run_skill(checkout, ["-m", "color_grading.cli", "run", str(manifest), "--json",
                                                "--workspace", str(workspace), "--allowed-input", str(workspace),
                                                "--ffmpeg-skill", str(ROOT / "ffmpeg-skill"), "--timeout", "55"],
                                     workspace, python_root=ROOT / checkout / "src")
            if not corrected.is_file():
                raise EditingSkillError(f"调色未产出预览：{str(result)[-500:]}")
            sheets = await asyncio.gather(*(
                build_seam_contact_sheet(path, start=0, end=end-start, before=before,
                                         unit_id=label, version=clip.video_version or 1)
                for path, label in ((staged, "SOURCE"), (corrected, "GRADE"))
            ))
            if not all(sheets):
                raise EditingSkillError("调色前后缺少可比较的画面。")
        return ToolOutcome(value={"revision": value.revision, "version": clip.video_version,
                                  "source_start_seconds": start, "source_end_seconds": end,
                                  "source_ycbcr": sheets[0].ycbcr, "graded_ycbcr": sheets[1].ycbcr,
                                  "preview_uses_full_strength": True,
                                  "operation": {"op": "set_grade", "clip": clip.id, "grade": value.grade.model_dump()},
                                  "images": [ToolImage(sheet.jpeg, "image/jpeg") for sheet in sheets]})
    except _SKILL_ERRORS as exc:
        return _error(exc)


async def plan_bgm_ducking(
    request: ToolRequest[DuckBgmRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    project = scope.project_name
    try:
        read = await EditTimelineService(services.projects).read(project, value.timeline, sync_script=False)
        if read.revision != value.revision:
            raise EditTimelineError("revision_conflict", "时间线已更新，请按最新修订重试。")
        if not read.bgm:
            return ToolOutcome(value={"revision": read.revision, "status": "no_bgm", "operations": []})
        if value.regions is None:
            regions = await _final_cut_service(services).narration_regions(project, value.timeline, revision=value.revision)
        else:
            regions = [(region.start, region.end) for region in value.regions]
        if not regions:
            return ToolOutcome(value={"revision": read.revision, "status": "no_speech", "operations": []})
        checkout = "vidmoat-skills"
        entry = ROOT / checkout / "skills/core/audio-ducking/scripts/duck_envelope.py"
        with TemporaryDirectory(prefix="juling-edit-") as directory:
            workspace = Path(directory)
            manifest = workspace / "speech.json"
            operations = []
            for clip in read.bgm:
                windows = [(max(start, clip.start) - clip.start, min(end, clip.end) - clip.start)
                           for start, end in regions if end > clip.start and start < clip.end]
                if not windows:
                    continue
                manifest.write_text(json.dumps(windows), encoding="utf-8")
                result = await run_skill(checkout, [str(entry), str(manifest), "--format", "json",
                                                    "--depth-db", str(value.depth_db)], workspace,
                                         python_root=entry.parent)
                points = {round(time * 1_000_000): db for time, db in result["keyframes"]}
                operations.append({"op": "set_bgm_envelope", "clip": clip.id, "points": [
                    {"time_us": time, "db": points[time]} for time in sorted(points)
                ]})
        return ToolOutcome(value={"revision": read.revision, "status": "planned", "operations": operations})
    except _SKILL_ERRORS as exc:
        return _error(exc)


async def review_final_cut(
    request: ToolRequest[ReviewCutRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    project = scope.project_name
    service = _final_cut_service(services)
    try:
        read = await EditTimelineService(services.projects).read(project, value.timeline, sync_script=False)
        if read.revision != value.revision:
            raise EditTimelineError("revision_conflict", "时间线已更新，请按最新修订重试。")
        with TemporaryDirectory(prefix="juling-edit-") as directory:
            workspace = Path(directory)
            output, plan, revision = await service.render_review_copy(project, value.timeline, workspace,
                                                                      revision=value.revision)
            clips = plan.clips
            boundaries = {left.clip.clip_id: (left, right) for left, right in zip(clips, clips[1:])}
            fps = plan.profile.fps
            checkout = "broomva-skills"
            scripts = ROOT / checkout / "skills/video/video-cut/scripts"
            measurements = []
            images = []
            loudness = await run_skill("ffmpeg-skill", [str(ROOT / "ffmpeg-skill/scripts/loudness.py"),
                                                        str(output), "--measure-only"], workspace,
                                       python_root=ROOT / "ffmpeg-skill/scripts")
            for left_id in dict.fromkeys(value.left_clips):
                if left_id not in boundaries:
                    measurements.append({"left_clip": left_id, "status": "seam_not_found"})
                    continue
                left, right = boundaries[left_id]
                cut = right.start_frame / fps
                basic = await run_skill(checkout, ["-c", "import json, sys; from pathlib import Path; "
                                                 "from self_eval import inspect_boundary; "
                                                 "print(json.dumps(inspect_boundary(sys.argv[1], float(sys.argv[2]), "
                                                 "0.1, Path.cwd(), True)))", str(output), str(cut)],
                                        workspace, python_root=scripts)
                basic.pop("frame", None)
                item = {"left_clip": left_id, "right_clip": right.clip.clip_id, "cut_seconds": cut,
                        "basic": basic, "sides": [],
                        "mix_levels": await audio_levels(output, max(0.0, cut - 0.16),
                                                         min(plan.duration_seconds, cut + 0.16) - max(0.0, cut - 0.16),
                                                         max(0.0, cut - 0.16) - cut, 1.0, [])}
                for side, before, start, end in (("left", True, left.start_frame / fps, cut),
                                                  ("right", False, cut, right.end_frame / fps)):
                    sheet = await build_seam_contact_sheet(output, start=start, end=end, before=before,
                                                          unit_id=f"{side} {left_id}", version=revision)
                    if sheet:
                        images.append(ToolImage(sheet.jpeg, "image/jpeg"))
                        item["sides"].append({"side": side, "image": len(images), "ycbcr": sheet.ycbcr})
                    else:
                        item["sides"].append({"side": side, "status": "unmeasurable"})
                measurements.append(item)
        return ToolOutcome(value={"revision": revision, "output_fps": fps, "loudness": loudness,
                                  "seams": measurements, "images": images})
    except _SKILL_ERRORS as exc:
        return _error(exc)


def _tool(name, description, request_model, handler, *, images=False):
    return ToolDeclaration(
        name=name, description=description, request_model=request_model, migration=BLOCKED,
        domain_key="editing_skill", handler=handler,
        projection=lambda value: {"editing_skill": {key: item for key, item in value.items() if key != "images"}},
        images=(lambda value: value["images"]) if images else None,
    )


EDITING_SKILL_TOOLS = (
    _tool("analyze_clip_media", "按当前修订的片段入出点查画面质量、时间戳、底噪和静音。供调色、降噪和压缩前取证。"
          "时间戳取自安全转封装/转码的分析片段，不代表源文件口型同步。", ClipMediaRequest, analyze_clip_media),
    _tool("preview_clip_grade", "试调片段头或尾部一秒的曝光和色温，返回前后联系表及可提交的 set_grade 操作。"
          "只读预览。", PreviewGradeRequest, preview_clip_grade, images=True),
    _tool("plan_bgm_ducking", "按项目实际旁白摆放计算 BGM 压低曲线，也可传入人工核对的成片语音区间（秒）。"
          "返回 edit_timeline 可提交的 set_bgm_envelope 操作。", DuckBgmRequest, plan_bgm_ducking),
    _tool("review_final_cut", "按项目默认旁白与字幕选项临时渲染指定修订，按左侧片段 ID 返回切点连续帧、"
          "黑帧和音频峰值疑点，及整条混音 LUFS 和真峰值。每批最多四个切点。", ReviewCutRequest,
          review_final_cut, images=True),
)
