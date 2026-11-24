"""剪辑切点的源画面与原声测量。"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from statistics import median
from struct import unpack
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lib.artifacts.version_manager import VersionManager
from lib.edit_timeline import EditTimelineError, EditTimelineService
from lib.edit_timeline.readout import ClipView
from lib.edit_timeline.sources import load_episode_script_units
from lib.final_cut.basis import provider_audio_recorded, version_snapshot
from lib.final_cut.ffmpeg_render import source_audio_filters
from lib.final_cut.render_plan import FINAL_CUT_FPS
from lib.infra.ffmpeg import FfmpegUnavailableError, ffmpeg_executable, local_file_input
from lib.infra.media_probe import MediaProbeError
from lib.infra.subprocess_deadline import SubprocessDeadlineExceeded, run_with_deadline
from lib.video_review.contact_sheet import ContactSheetError, build_seam_contact_sheet
from server.agent_toolset.declaration import BLOCKED, ToolDeclaration, ToolImage
from server.media_tools.context import tool_problem
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest

_SAMPLE_RATE = 16_000
_BIN_MS = 20
_WINDOW_MS = 320


class InspectTimelineSeamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline: str = Field(min_length=1, description="read_timeline 的时间线 ID。")
    left_clip: str = Field(min_length=1, description="待检查切点左侧的片段 ID，例如 c3。")


def _dbfs(amplitude: float) -> float | None:
    return round(20 * math.log10(amplitude / 32768), 1) if amplitude > 0 else None


async def audio_levels(path: Path, start: float, duration: float, offset: float, gain: float, filters: list[str]) -> dict[str, Any]:
    if not gain:
        return {"status": "muted"}
    if duration <= 0:
        return {"status": "outside_source"}
    result = await run_with_deadline(
        [
            ffmpeg_executable(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.6f}",
            *local_file_input(path), "-t", f"{duration:.6f}", "-map", "0:a:0", "-ac", "2",
            "-af", ",".join([f"aresample={_SAMPLE_RATE}:async=1:first_pts=0", *filters, f"volume={gain:.6f}"]), "-f", "s16le", "-",
        ],
        deadline_seconds=10,
        capture_stdout=True,
        capture_stderr=True,
    )
    if result.returncode:
        return {"status": "no_audio" if b"matches no streams" in result.stderr else "unreadable"}
    samples = unpack(f"<{len(result.stdout) // 2}h", result.stdout)
    bin_size = 2 * _SAMPLE_RATE * _BIN_MS // 1000
    bins = []
    for index in range(0, len(samples), bin_size):
        values = samples[index:index + bin_size]
        bins.append({
            "start_ms": round(1000 * (offset + index / (2 * _SAMPLE_RATE))),
            "end_ms": round(1000 * (offset + (index + len(values)) / (2 * _SAMPLE_RATE))),
            "rms_dbfs": _dbfs(math.sqrt(sum(value * value for value in values) / len(values))),
            "peak_dbfs": _dbfs(max(map(abs, values))),
        })
    return {"status": "ok" if bins else "outside_audio", "levels": bins}


async def _measure_side(
    clip: ClipView,
    path: Path,
    *,
    before: bool,
    provider_audio: bool,
) -> tuple[dict[str, Any], ToolImage | None]:
    source_duration = clip.source_duration or 0
    start, end = source_bounds(clip)
    if before:
        edge = end
        audio_end = end
        audio_start = max(start, end + clip.hold - _WINDOW_MS / 1000)
        audio_offset = audio_start - end - clip.hold
    else:
        edge = start
        audio_start, audio_end, audio_offset = start, min(end, start + _WINDOW_MS / 1000), 0.0

    gain = clip.source_volume if provider_audio else 0.0
    audio, picture = await asyncio.gather(
        audio_levels(path, audio_start, audio_end - audio_start, audio_offset, gain, source_audio_filters(clip.audio_processing)),
        build_seam_contact_sheet(
            path, start=start, end=end, before=before, unit_id=clip.unit_id, version=clip.video_version or 1
        ),
        return_exceptions=True,
    )
    if isinstance(audio, FfmpegUnavailableError) or isinstance(picture, FfmpegUnavailableError):
        raise FfmpegUnavailableError("随包 ffmpeg 不可用。")
    if isinstance(audio, (SubprocessDeadlineExceeded, OSError)):
        audio = {"status": "unreadable"}
    if isinstance(audio, BaseException):
        raise audio
    if isinstance(picture, (MediaProbeError, ContactSheetError, OSError)):
        picture = None
    if isinstance(picture, BaseException):
        raise picture
    return {
        "clip": clip.id,
        "unit_id": clip.unit_id,
        "version": clip.video_version,
        "source_edge_seconds": round(edge, 3),
        "unused_head_seconds": round(start, 3),
        "unused_tail_seconds": round(max(0, source_duration - end), 3),
        "hold_ms": round(clip.hold * 1000),
        "grade": clip.grade.model_dump() if clip.grade else None,
        "source_picture_ycbcr": picture.ycbcr if picture else (),
        "frames": [
            {"source_seconds": round(frame.time_seconds, 4),
             "relative_ms": round(1000 * (frame.time_seconds - edge - (clip.hold if before else 0)))}
            for frame in picture.frames
        ] if picture else [],
        "audio": audio,
    }, ToolImage(picture.jpeg, "image/jpeg") if picture else None


async def seam_context(project: str, timeline: str, services: Services):
    readout = await EditTimelineService(services.projects).read(project, timeline, sync_script=False)
    clips = [clip for clip in readout.clips if clip.status != "unit_deleted" and clip.duration > 0]

    def snapshots():
        script = load_episode_script_units(services.projects, project, readout.timeline.episode)
        root = services.projects.get_project_path(project)
        versions = VersionManager(root)
        return {
            (clip.unit_id, clip.video_version): version_snapshot(
                root, versions, script.video_resource_type, clip.unit_id, clip.video_version
            )
            for clip in clips if clip.status == "ready" and clip.video_version is not None
        }

    return readout, clips, await asyncio.to_thread(snapshots)


def source_bounds(clip: ClipView) -> tuple[float, float]:
    start = clip.trim.source_in if clip.trim is not None and clip.trim.basis_version == clip.video_version else 0
    return start, min(clip.source_duration or 0, start + max(0.0, clip.duration - clip.hold))


async def _inspect_pair(left, right, snapshots, *, include_images: bool):
    result = {
        "cut_seconds": right.start,
        "audio_overlap_frames": left.audio_overlap_frames,
        "left": {"clip": left.id, "version": left.video_version},
        "right": {"clip": right.id, "version": right.video_version},
    }
    paths = [snapshots.get((clip.unit_id, clip.video_version)) for clip in (left, right)]
    if not all(paths):
        return {**result, "status": "failed", "reason": "seam_source_missing"}, []
    measured = await asyncio.gather(*(
        _measure_side(clip, path, before=before, provider_audio=provider_audio_recorded(record))
        for clip, (path, record), before in zip((left, right), paths, (True, False), strict=True)
    ))
    images = []
    for key, (info, image) in zip(("left", "right"), measured, strict=True):
        result[key] = info
        if include_images and image is not None:
            images.append(image)
            info["image"] = len(images)
        if not include_images:
            levels = info["audio"].pop("levels", [])
            info["audio"]["edge_levels"] = levels[-4:] if key == "left" else levels[:4]
    left_picture, right_picture = (result[side]["source_picture_ycbcr"] for side in ("left", "right"))
    if left_picture and right_picture:
        result["source_delta_ycbcr"] = [
            round(median(right_channel) - median(left_channel), 2)
            for left_channel, right_channel in zip(zip(*left_picture), zip(*right_picture), strict=True)
        ]
    audio = [result[side]["audio"]["status"] for side in ("left", "right")]
    result["picture_status"] = "measured" if left_picture and right_picture else "failed"
    result["audio_status"] = ("failed" if "unreadable" in audio else
                              "not_applicable" if all(state != "ok" for state in audio) else "measured")
    result["status"] = "failed" if "failed" in (result["picture_status"], result["audio_status"]) else "measured"
    # Video bounds only give an upper bound on audio handles; the renderer checks the audio stream duration.
    if audio == ["ok", "ok"] and not left.hold:
        result["estimated_audio_handle_frames"] = {
            "before_frames": int((result["right"]["unused_head_seconds"] + 0.0005) * FINAL_CUT_FPS),
            "after_frames": int((result["left"]["unused_tail_seconds"] + 0.0005) * FINAL_CUT_FPS),
        }
    return result, images


class ScanTimelineSeamsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=1, description="期望的当前修订号。")
    start: int = Field(default=0, ge=0, description="从第几个切点起查，0 起算。")
    limit: int = Field(default=32, ge=1, le=32, description="本批切点数。带图时最多 4 个。")
    include_images: bool = False


async def scan_timeline_seams(
    request: ToolRequest[ScanTimelineSeamsRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    value = request.value
    try:
        readout, clips, snapshots = await seam_context(scope.project_name, value.timeline, services)
        if value.revision is not None and readout.revision != value.revision:
            return tool_problem("时间线已更新，重读后重新审阅。", code="revision_conflict")
        pairs = list(zip(clips, clips[1:]))
        stop = min(len(pairs), value.start + min(value.limit, 4 if value.include_images else 32))
        seams, images = [], []
        for left, right in pairs[value.start:stop]:
            entry, pictures = await _inspect_pair(left, right, snapshots, include_images=value.include_images)
            for side in ("left", "right"):
                if "image" in entry[side]:
                    entry[side]["image"] += len(images)
            seams.append(entry)
            images.extend(pictures)
    except EditTimelineError as exc:
        return tool_problem(str(exc), code=exc.code)
    except FileNotFoundError:
        return tool_problem("时间线或项目素材已不存在。", code="file_not_found")
    except FfmpegUnavailableError:
        return tool_problem("随包 ffmpeg 不可用。", code="ffmpeg_unavailable")
    return ToolOutcome(value={"revision": readout.revision, "output_fps": FINAL_CUT_FPS,
                              "total": len(pairs), "next_start": stop if stop < len(pairs) else None,
                              "seams": seams, "images": images})


async def inspect_timeline_seam(
    request: ToolRequest[InspectTimelineSeamRequest], scope: ProjectScope, _caller: CallerContext, services: Services,
) -> ToolOutcome[dict[str, Any]]:
    try:
        readout, clips, snapshots = await seam_context(scope.project_name, request.value.timeline, services)
        pair = next(((left, right) for left, right in zip(clips, clips[1:]) if left.id == request.value.left_clip), None)
        if pair is None:
            return tool_problem("指定片段需要一个相邻的后续片段。", code="seam_not_found")
        entry, images = await _inspect_pair(*pair, snapshots, include_images=True)
        if entry.get("reason") == "seam_source_missing":
            return tool_problem("切点两侧都需要可用的视频版本。", code="seam_source_missing")
        return ToolOutcome(value={"revision": readout.revision, "output_fps": FINAL_CUT_FPS, **entry, "images": images})
    except EditTimelineError as exc:
        return tool_problem(str(exc), code=exc.code)
    except FileNotFoundError:
        return tool_problem("时间线或项目素材已不存在。", code="file_not_found")
    except FfmpegUnavailableError:
        return tool_problem("随包 ffmpeg 不可用。", code="ffmpeg_unavailable")


SCAN_TIMELINE_SEAMS = ToolDeclaration(
    name="scan_timeline_seams",
    description="按顺序扫描时间线所有相邻切点，返回源帧平均 Y/Cb/Cr、原声边缘 RMS/峰值、素材版本和失败项。"
                "颜色指标取未调色源帧，仅用于定位疑点。带图每批最多四个切点，继续用 next_start 分页。",
    request_model=ScanTimelineSeamsRequest,
    migration=BLOCKED,
    domain_key="timeline_seams",
    handler=scan_timeline_seams,
    projection=lambda value: {"timeline_seams": {key: item for key, item in value.items() if key != "images"}},
    images=lambda value: value["images"],
)


INSPECT_TIMELINE_SEAM = ToolDeclaration(
    name="inspect_timeline_seam",
    description=(
        "检查剪辑时间线上指定切点的音画衔接。用左侧 clip ID 定位切点，返回当前修订号、两侧实际边缘帧图片、"
        "源时间、可借用的画面余量、切点前后各 320 毫秒内每 20 毫秒的原声 RMS 与峰值 dBFS。"
        "负时间是切点前，正时间是切点后，dBFS 为 null 表示数字静音。测量对象是按片段音量缩放的源原声，"
        "不含旁白、BGM 或已设置的交叠混音。"
        "用画面与瞬态时序检查动作接续、响度突变、静音空隙；语义与口型对齐需能辨认对应事件才可判断。"
        "修正用 edit_timeline 的 set_trim、set_hold、set_transition 或 set_audio_overlap。"
    ),
    request_model=InspectTimelineSeamRequest,
    migration=BLOCKED,
    domain_key="timeline_seam",
    handler=inspect_timeline_seam,
    projection=lambda value: {"timeline_seam": {key: item for key, item in value.items() if key != "images"}},
    images=lambda value: value["images"],
)
