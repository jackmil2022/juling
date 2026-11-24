"""Run one H3 generation request as short Pika/upscale/TaoMate clips."""

from __future__ import annotations

import asyncio
import json
import math
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from secrets import randbelow
from tempfile import TemporaryDirectory
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx

from juling_market_core.comfyui.bindings import bound_fps, targets_of
from juling_market_core.comfyui.workflow import is_link, node_inputs
from juling_market_core.video_backend_contract import ResumeExpiredError, VideoCapabilityError, VideoGenerationRequest, VideoGenerationResult
from lib.backends.artifact_download_guard import artifact_http_client
from lib.backends.backend_runtime import notify_provider_response
from lib.infra.ffmpeg import ffmpeg_executable
from lib.script.reference_video.continuity_clip import continuity_clip
from lib.script.reference_video.text_parser import UNIT_TIME_RANGE, UNTIMED_SPEECH_APPENDIX
from lib.script.reference_video.duration_slots import VIDEO_REFERENCE_SLOTS

from .capabilities import CONTINUOUS_H3_DURATIONS, continuous_director_node, is_pika_ref2va
from .comfyui_client import client_id_for, upload_filename
from .comfyui_execution import HTTP_TIMEOUT_SECONDS
from .failures import EXECUTION_ERROR, ComfyuiError
from .node_pool import (
    ComfyuiDispatchPool, ComfyuiPoolConfig, comfyui_dispatch_node, comfyui_live_pool, standalone_comfyui_pool,
)
from .request_builder import BuiltWorkflow, build_workflow, workflow_sha256
from .seam_repair import FPS, StitchPart, stitch_clips

if TYPE_CHECKING:
    from .comfyui_backend import ComfyuiVideoBackend

JOB_ID = "juling-h3-continuous-v1"
MAX_NODES = 20
_LIST_KEYS = ("reference_images", "reference_videos", "reference_audio_files")
_MEDIA_KEYS = ("start_image", "end_image", *_LIST_KEYS, "previous_video", "next_video")
_SEED_LIMIT = 2**53 - 1  # ComfyUI's UI stores integer widget values as JavaScript numbers.


@dataclass(frozen=True)
class Clip:
    start: int
    end: int
    prompt: str

    @property
    def seconds(self) -> int:
        return self.end - self.start


def _error(detail: str) -> ComfyuiError:
    return ComfyuiError(EXECUTION_ERROR, node="剧灵 连续视频", detail=detail)


def plan_clips(prompt: str, duration: int, *, allow_unsplit: bool = False, legacy: bool = False) -> list[Clip]:
    if duration not in CONTINUOUS_H3_DURATIONS and not (legacy and duration in (2, 3)):
        raise _error("H3 连续视频支持 4–20 秒；内部片段 2–8 秒。")
    prompt = prompt.replace("\r\n", "\n")
    ranges = list(UNIT_TIME_RANGE.finditer(prompt))
    if len(ranges) <= 1 and duration <= 8:
        return [Clip(0, duration, prompt)]
    if (allow_unsplit and not legacy and ranges
            and UNTIMED_SPEECH_APPENDIX.search(prompt, ranges[-1].end())):
        # There is no defensible way to assign untimed dialogue to separate clips.
        return [Clip(0, duration, prompt)]
    times = [(float(m[1]), float(m[2])) for m in ranges]
    if (not times or times[0][0] != 0 or times[-1][1] != duration
        or any(start >= end for start, end in times)
        or any(left[1] != right[0] for left, right in zip(times, times[1:]))):
        if allow_unsplit:
            return [Clip(0, duration, prompt)]
        raise _error("时间轴需按整秒或半秒区间连续覆盖请求时长，例如 [0s-3.5s]。")

    # Keep complete blocks together and minimize provider calls before balancing their lengths.
    n = len(times)
    best: dict[int, tuple[float, list[int]]] = {n: (0, [])}
    for first in range(n - 1, -1, -1):
        for last in range(first + 1, n + 1):
            seconds = times[last - 1][1] - times[first][0]
            if seconds > 8:
                break
            if seconds >= 2 and seconds.is_integer() and last in best:
                score = ((seconds - 4)**2 + 2 if legacy else (seconds - 8)**2 + 100) + best[last][0]
                if first not in best or score < best[first][0]:
                    best[first] = (score, [last, *best[last][1]])
    if 0 not in best:
        if allow_unsplit:
            return [Clip(0, duration, prompt)]
        raise _error("现有时间轴不能分成 2–8 秒的片段。请在动作或台词结束处增加时间区间。")

    prefix = prompt[:ranges[0].start()].strip()
    blocks = [prompt[m.end():ranges[i + 1].start() if i + 1 < n else len(prompt)].strip()
              for i, m in enumerate(ranges)]
    tail = blocks[-1].split("\n\n", 1)
    blocks[-1], suffix = tail[0], tail[1] if len(tail) == 2 else ""
    clips = []
    first = 0
    for last in best[0][1]:
        start = times[first][0]
        body = "\n\n".join(f"[{a-start:g}s-{b-start:g}s]\n{blocks[i]}" for i, (a, b) in enumerate(times)
                           if first <= i < last)
        clips.append(Clip(int(start), int(times[last - 1][1]), "\n\n".join(x for x in (prefix, body, suffix) if x)))
        first = last
    return clips


def next_clip(count: int, complete: set[int], active: set[int], failed: set[int]) -> int | None:
    settled = complete | failed
    for phase in range(3):
        for index in range(phase, count, 3):
            if index in settled or index in active:
                continue
            if all(other % 3 >= phase or other in settled
                   for other in (index - 1, index + 1) if 0 <= other < count):
                return index
    return None


def add_boundary_guides(
    built: BuiltWorkflow,
    bindings: Mapping[str, Any],
    *,
    seconds: int,
    before: str | None,
    after: str | None,
) -> BuiltWorkflow:
    graph = built.workflow
    frames = targets_of(bindings.get("frames"))
    if len(frames) != 1 or bound_fps(graph, bindings) != FPS:
        raise _error("H3 连续端点需要一个帧数绑定，输出帧率必须为 24 fps。")
    ref = graph.get(str(frames[0]["node"]), {})
    vae = node_inputs(ref).get("vae")
    if ref.get("class_type") != "MiniMaxH3ReferenceToVideo" or frames[0]["input"] != "length" or not is_link(vae):
        raise _error("帧数须绑定到 MiniMaxH3ReferenceToVideo.length，并连接视频 VAE。")
    length = 5 + 17 * math.ceil((seconds * FPS + 1 - 5) / 17)
    ref["inputs"]["length"] = length
    samplers = [node_inputs(node) for node in graph.values() if node.get("class_type") == "SamplerCustomAdvanced"]
    guiders = [graph.get(link[0], {}) for inputs in samplers if is_link(link := inputs.get("guider"))]
    if len(samplers) != 2 or len(guiders) != 2 or any(node.get("class_type") != "BasicGuider" for node in guiders):
        raise _error("连续端点须有 Pika 和 TaoMate 两个 SamplerCustomAdvanced / BasicGuider。")

    def add(name: str, node_class: str, **inputs: Any) -> list[Any]:
        key = f"juling_continuity_{name}"
        if key in graph:
            raise _error(f"工作流节点 ID 冲突：{key}")
        graph[key] = {"class_type": node_class, "inputs": inputs}
        return [key, 0]

    for name, filename, start, frame in (("before", before, -5, 0), ("after", after, 0, length - 5)):
        if not filename:
            continue
        source = add(f"{name}_load", "LoadVideo", file=filename)
        images = add(f"{name}_split", "GetVideoComponents", video=source)
        anchor = add(f"{name}_frames", "ImageFromBatch", image=images, batch_index=start, length=5)
        for index, (sampler, guider) in enumerate(zip(samplers, guiders, strict=True)):
            inputs = guider["inputs"]
            inputs["conditioning"] = add(f"{name}_guide_{index}", "MiniMaxH3AddGuide",
                positive=inputs["conditioning"], latent=sampler["latent_image"], vae=vae, image=anchor, frame_idx=frame)
    return replace(built, frames=length, workflow_sha256=workflow_sha256(graph))


def _cache_path(output: Path) -> Path:
    return output.with_suffix(".h3-continuous")


def cleanup_continuous_video(output: Path) -> None:
    folder = _cache_path(output)
    if not folder.is_dir() or folder.is_symlink() or folder.resolve() != output.parent.resolve() / folder.name:
        return
    if not (folder / "state.json").is_file():
        return
    for path in folder.iterdir():
        if path.is_file() and re.fullmatch(r"state\.json(?:\.tmp)?|clip-\d+(?:\.raw)?\.mp4|media-\w+-\d+\.[A-Za-z0-9]+", path.name):
            path.unlink()
    if not any(folder.iterdir()):
        folder.rmdir()


class _Run:
    def __init__(self, backend: ComfyuiVideoBackend, request: VideoGenerationRequest, folder: Path,
                 fallback_pool: ComfyuiDispatchPool | None, *, resume: bool) -> None:
        self.backend, self.request, self.folder = backend, request, folder
        # A legacy prompt without safe cut points should still run once, with its dialogue intact.
        self.clips = plan_clips(
            request.prompt, request.duration_seconds,
            allow_unsplit=continuous_director_node(backend._definition) is not None,
            legacy=resume and request.duration_seconds < 4,
        )
        fingerprint_input = {
            "definition": backend._definition,
            "clips": [clip.prompt for clip in self.clips],
            "duration": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
        }
        self.fingerprint = workflow_sha256(fingerprint_input)
        self.state_path = folder / "state.json"
        if resume and self.state_path.is_file():
            try:
                old_fingerprint = json.loads(self.state_path.read_text(encoding="utf-8")).get("fingerprint")
            except (OSError, ValueError, AttributeError):
                old_fingerprint = None  # prepare() reports corrupt state without submitting.
            if old_fingerprint and old_fingerprint != self.fingerprint:
                old_clips = plan_clips(request.prompt, request.duration_seconds,
                                       allow_unsplit=continuous_director_node(backend._definition) is not None, legacy=True)
                if workflow_sha256({**fingerprint_input, "clips": [clip.prompt for clip in old_clips]}) == old_fingerprint:
                    self.clips, self.fingerprint = old_clips, old_fingerprint
        self.label = request.task_id or uuid4().hex
        live = comfyui_live_pool.get()
        if live is not None:
            self.pool, get_config = live
            self.config = lambda: get_config(backend.name)
        else:
            assert fallback_pool is not None
            self.pool = fallback_pool
            config = ComfyuiPoolConfig(backend._nodes, backend._api_key, (backend._definition.get("auth") or {},))
            self.config = lambda: config

    def save(self) -> None:
        pending = self.state_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        pending.replace(self.state_path)

    def prepare(self, *, resume: bool) -> None:
        if self.folder.is_symlink() or self.folder.resolve() != self.request.output_path.parent.resolve() / self.folder.name:
            raise _error("分段检查点目录无效。")
        if resume:
            if not self.state_path.is_file() or self.state_path.is_symlink():
                raise ResumeExpiredError(job_id=JOB_ID, provider=self.backend.name)
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("fingerprint") != self.fingerprint or len(self.state.get("jobs", ())) != len(self.clips):
                raise _error("续跑时工作流或时间轴已变更，请恢复提交时的配置。")
        else:
            self._validate_reference_capacity()
            self.folder.mkdir(exist_ok=True, parents=True)
            if self.state_path.exists():
                raise _error("该任务已有分段检查点，请从检查点续跑。")
            media = {}
            for key in _MEDIA_KEYS:
                value = getattr(self.request, key)
                paths = (value or ()) if key in _LIST_KEYS else ([value] if value else [])
                for index, source in enumerate(paths):
                    suffix = Path(source).suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]+", suffix):
                        raise _error(f"参考素材扩展名无效：{key}")
                    path = self.folder / f"media-{key}-{index}{suffix}"
                    shutil.copyfile(source, path)
                    media.setdefault(key, []).append(path.name)
            seed = self.request.seed if self.request.seed is not None else randbelow(_SEED_LIMIT)
            self.state = {"fingerprint": self.fingerprint, "media": media, "jobs": [None] * len(self.clips), "seed": seed,
                          "video_size_version": 2}
            self.save()
        values = {}
        for key in _MEDIA_KEYS:
            names = self.state["media"].get(key, [])
            if any(not re.fullmatch(rf"media-{key}-\d+\.[a-z0-9]+", name) for name in names):
                raise _error("分段检查点的素材路径无效。")
            paths = [self.folder / name for name in names]
            if any(not path.is_file() or path.is_symlink() for path in paths):
                raise _error("分段检查点缺少参考素材。")
            values[key] = paths if key in _LIST_KEYS else next(iter(paths), None)
        self.request = replace(self.request, **values)
        if resume:
            self._validate_reference_capacity(resume=True)

    def _validate_reference_capacity(self, *, resume: bool = False) -> None:
        definition = self.backend._definition
        if continuous_director_node(definition) is None:
            return
        if (self.request.start_image or self.request.end_image) and not is_pika_ref2va(definition):
            return
        slots = len(targets_of(definition["bindings"].get("reference_videos")))
        last = len(self.clips) - 1
        for index in range(len(self.clips)):
            if resume and self.state["jobs"][index] is not None:
                continue
            before = index > 0 or self.request.previous_video is not None
            after = self.request.next_video is not None if index == last else (
                index % 3 == 2 or resume and self.state["jobs"][index + 1] is not None
            )
            count = len(self.request.reference_videos or ()) + int(before) + int(after)
            if count > slots:
                raise VideoCapabilityError("video_reference_videos_exceeded", model=self.backend.model, limit=slots, count=count)
            total = count + len(self.request.reference_images or ()) + len(self.request.reference_audio_files or ())
            if total > VIDEO_REFERENCE_SLOTS:
                raise _error(f"H3 连续片段共占用 {total} 个参考槽位，上限 {VIDEO_REFERENCE_SLOTS}。")

    def clip_path(self, index: int) -> Path:
        return self.folder / f"clip-{index}.mp4"

    async def render_clip(
        self, http: httpx.AsyncClient, index: int, url: str, adjacent: tuple[int, ...], *, api_key: str,
    ) -> None:
        backend = self.backend._bound_to(url, api_key=api_key)
        job = self.state["jobs"][index]
        clip = self.clips[index]
        label = f"{self.label}-{index + 1}"
        if job is None:
            request = replace(self.request, prompt=clip.prompt, output_path=self.clip_path(index),
                              duration_seconds=clip.seconds, seed=(self.state["seed"] + index) % _SEED_LIMIT,
                              previous_video=self.request.previous_video if index == 0 else None,
                              next_video=self.request.next_video if index == len(self.clips) - 1 else None)
            director = continuous_director_node(backend._definition)
            bindings = backend._definition["bindings"]
            keyframes = bool(request.start_image or request.end_image)
            if director is not None:
                request = replace(request, start_image=request.start_image if index == 0 else None,
                                  end_image=request.end_image if index == len(self.clips) - 1 else None)
                if keyframes and not is_pika_ref2va(backend._definition):
                    adjacent = tuple(i for i in adjacent if not (
                        request.start_image if i < index else request.end_image
                    ))
                previous = request.previous_video
                following = request.next_video
                if index - 1 in adjacent:
                    previous, _ = await continuity_clip(self.clip_path(index - 1), self.clip_path(index).parent / ".continuity", "previous_video")
                if index + 1 in adjacent:
                    following, _ = await continuity_clip(self.clip_path(index + 1), self.clip_path(index).parent / ".continuity", "next_video")
                request = replace(request, previous_video=previous, next_video=following)
                if not keyframes or is_pika_ref2va(backend._definition):
                    slots = len(targets_of(bindings.get("reference_videos")))
                    count = len(request.reference_videos or ())
                    count += sum(path is not None for path in (request.previous_video, request.next_video))
                    if count > slots:
                        raise VideoCapabilityError("video_reference_videos_exceeded", model=backend.model, limit=slots, count=count)
            media = await backend._upload_media(http, request, job_label=label)
            if director is not None:
                media = replace(media, keyframe_mode=keyframes and not is_pika_ref2va(backend._definition))
            else:
                available = {}
                for other in adjacent:
                    role = "previous_video" if other < index else "next_video"
                    path, _ = await continuity_clip(self.clip_path(other), self.clip_path(index).parent / ".continuity", role)
                    available[other] = await backend._client.upload_media(
                        http, path, filename=upload_filename(label, "continuity", path, other)
                    )
                before, after = available.get(index - 1), available.get(index + 1)
            built = await asyncio.to_thread(build_workflow, backend._definition, prompt=clip.prompt,
                aspect_ratio=request.aspect_ratio, duration_seconds=clip.seconds, resolution=request.resolution,
                media=media, seed=request.seed,
                # 旧检查点的剩余片段须与已提交片段沿用同一宽高算法。
                legacy_video_size=self.state.get("video_size_version") != 2)
            if director is None:
                built = add_boundary_guides(built, bindings, seconds=clip.seconds, before=before, after=after)
            job = {"url": url, "id": None, "workflow_sha256": built.workflow_sha256}
            if any(built.seam_trim):
                job["seam_trim"] = built.seam_trim
            self.state["jobs"][index] = job
            # A process can exit after POST is accepted but before the prompt_id arrives. Never replay that POST.
            self.save()
            job["id"] = await backend._client.submit_prompt(http, built.workflow, client_id=client_id_for(label),
                record=lambda stage, body: self.record(index, stage, body))
            self.save()
        elif not job["id"]:
            raise _error(f"片段 {index + 1} 的提交结果未知，未重复提交。请到该机器的队列核对。")
        path = self.clip_path(index)
        trim_head, trim_tail = job.get("seam_trim", (0, 0))
        needs_trim = bool(trim_head or trim_tail)
        fetched = path.with_suffix(".raw.mp4") if needs_trim else path
        try:
            await backend._execution.fetch_artifact(
                http,
                job["id"],
                output_path=fetched,
                poll_timeout_seconds=self.request.poll_timeout_seconds,
                record=lambda stage, body: self.record(index, stage, body),
                stop_on_cancel=False,  # A restarted parent must still be able to collect the remote clip.
            )
            if needs_trim:
                # Adjacent jobs must see the same boundary that will be used in the final edit.
                job["kept_frames"], = await stitch_clips(
                    [StitchPart(fetched, trim_head=trim_head, trim_tail=trim_tail)], path,
                    audio=self.request.generate_audio,
                )
        finally:
            if needs_trim:
                fetched.unlink(missing_ok=True)
        job["complete"] = True
        self.save()

    async def record(self, index: int, stage: Any, body: object) -> None:
        await notify_provider_response(self.request, stage, {"clip": index + 1, "response": body})

    async def execute(self) -> VideoGenerationResult:
        active: dict[int, asyncio.Task[None]] = {}
        errors: dict[int, Exception] = {}
        jobs = self.state["jobs"]
        complete = {i for i, job in enumerate(jobs) if job and job.get("complete") and self.clip_path(i).is_file()}
        dispatch = comfyui_dispatch_node.get()
        if dispatch is not None and dispatch.provider_id == self.backend.name:
            dispatch.release()
        last_progress = monotonic()
        try:
            async with artifact_http_client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as http:
                for i, job in enumerate(jobs):
                    if job and i not in complete:
                        live = self.config()
                        if live is None or job["url"] not in live.urls:
                            errors[i] = _error(f"片段 {i + 1} 原提交机器已移出供应商，请加回后续跑。")
                            continue
                        url = job["url"]
                        self.pool.hold(url)
                        active[i] = asyncio.create_task(self.render_clip(http, i, url, (), api_key=live.api_key))
                        active[i].add_done_callback(lambda _, held=url: self.pool.release(held))
                while len(complete) + len(errors) < len(self.clips):
                    config = self.config()
                    if config is not None:
                        while len(active) < min(MAX_NODES, len(config.urls)):
                            index = next_clip(len(self.clips), complete, set(active), set(errors))
                            if index is None:
                                break
                            url = self.pool.reserve(self.backend.name, config)
                            if url is None:
                                self.pool.ready(self.backend.name, config)
                                break
                            active[index] = asyncio.create_task(self.render_clip(
                                http, index, url, tuple(i for i in (index - 1, index + 1) if i in complete),
                                api_key=config.api_key,
                            ))
                            active[index].add_done_callback(lambda _, held=url: self.pool.release(held))
                    if active:
                        finished, _ = await asyncio.wait(active.values(), timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
                        for index in list(active):
                            if active[index] in finished:
                                try:
                                    await active.pop(index)
                                except Exception as exc:
                                    errors[index] = exc
                                else:
                                    complete.add(index)
                                last_progress = monotonic()
                    else:
                        if monotonic() - last_progress > self.request.poll_timeout_seconds:
                            raise ComfyuiError("comfyui_nodes_unreachable")
                        await asyncio.sleep(0.5)
            if errors:
                raise errors[min(errors)]
            kept_frames = await stitch_clips(
                [StitchPart(self.clip_path(i), job.get("kept_frames", clip.seconds * FPS))
                 for i, (clip, job) in enumerate(zip(self.clips, jobs, strict=True))],
                self.request.output_path, audio=self.request.generate_audio,
            )
        finally:
            for task in active.values():
                task.cancel()
            await asyncio.gather(*active.values(), return_exceptions=True)
        return VideoGenerationResult(video_path=self.request.output_path, provider=self.backend.name,
            model=self.backend.model, duration_seconds=self.request.duration_seconds, task_id=JOB_ID,
            seed=self.state["seed"], generate_audio=self.request.generate_audio, provenance={
                "continuous_clips": [{"start": clip.start, "end": clip.end, "prompt_id": job["id"],
                                      "workflow_sha256": job["workflow_sha256"], "kept_frames": frames,
                                      **({"seam_trim": job["seam_trim"]} if "seam_trim" in job else {})}
                                     for clip, job, frames in zip(self.clips, jobs, kept_frames, strict=True)],
            })


async def run_continuous(
    backend: ComfyuiVideoBackend, request: VideoGenerationRequest, *, resume: bool = False,
) -> VideoGenerationResult:
    await asyncio.to_thread(ffmpeg_executable)

    async def run(folder: Path, pool: ComfyuiDispatchPool | None) -> VideoGenerationResult:
        execution = _Run(backend, request, folder, pool, resume=resume)
        await asyncio.to_thread(execution.prepare, resume=resume)
        if not resume:
            # Store the aggregate handle before the first remote prompt is possible.
            await backend._persist_provider_job_id(request, JOB_ID, provider=backend.name)
        return await execution.execute()

    async def run_with_folder(pool: ComfyuiDispatchPool | None = None) -> VideoGenerationResult:
        if request.task_id is not None:
            return await run(_cache_path(request.output_path), pool)
        with TemporaryDirectory(dir=request.output_path.parent) as folder:
            return await run(Path(folder), pool)

    if comfyui_live_pool.get() is not None:
        return await run_with_folder()
    async with standalone_comfyui_pool() as pool:
        return await run_with_folder(pool)
