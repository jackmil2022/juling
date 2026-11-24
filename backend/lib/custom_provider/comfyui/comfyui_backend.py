"""ComfyUI 端点的视频调用通道。

不在 ``lib.backends.video_backends``：本 backend 的输入是一份 ComfyUI 端点定义（workflow + 节点绑定），
读它要用本包的构造层，而分层契约（``pyproject.toml`` ``[tool.importlinter]``）不允许 backend 层反向依赖
``lib.custom_provider``；方向与声明式运行时一致——上层消费下层，下层不知道端点定义的存在。

一次生成的四段：上传素材换回服务端认的引用名 → 在底稿深拷贝上构造实发 workflow → ``POST /prompt``
拿 ``prompt_id`` → 轮询 ``/history`` 到终态后按 ``output`` 绑定取产物下载入库。素材上传排在构造
之前，因为引用名要填进 workflow；``provider_job_id`` 的持久化排在轮询之前，因为进程在轮询中途重启
时，没落库的那笔任务就再也找不回来了。

第四段本身与媒体类型无关，落在 :mod:`.comfyui_execution`，与图像通道共用；本模块只管视频这一侧
独有的部分——由绑定表推出的能力声明、首尾帧与参考图的上传、续跑，以及把取回的产物装成
``VideoGenerationResult``。

续跑接的是第四段：``provider_job_id`` 就是 ``prompt_id``，前三段已经在上一个进程里发生过。取消与
超时则反过来——本地这一侧不要这次执行了，就顺手把远端也停掉，否则它会一直占着用户的显卡。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from juling_market_core.video_backend_contract import (
    ReferenceAudioMode,
    ResumeExpiredError,
    VideoAudioMode,
    VideoCapabilities,
    VideoCapabilityError,
    VideoGenerationRequest,
    VideoGenerationResult,
)

from lib.backends.artifact_download_guard import artifact_http_client
from lib.backends.backend_runtime import ProviderJobIdPersistenceMixin, notify_provider_response
from lib.custom_provider.comfyui.capabilities import (
    continuous_director_node,
    derive_video_capabilities,
    is_continuous_h3,
)
from lib.custom_provider.comfyui.comfyui_client import ComfyuiClient, client_id_for, upload_filename
from lib.custom_provider.comfyui.comfyui_execution import HTTP_TIMEOUT_SECONDS, ComfyuiExecution, PickedArtifact
from lib.custom_provider.comfyui.continuous_video import JOB_ID as CONTINUOUS_JOB_ID
from lib.custom_provider.comfyui.continuous_video import add_boundary_guides, run_continuous
from lib.custom_provider.comfyui.failures import EXECUTION_ERROR, ComfyuiError
from lib.custom_provider.comfyui.node_pool import comfyui_node_urls, generation_node
from lib.custom_provider.comfyui.request_builder import (
    BuiltWorkflow,
    MediaInputs,
    build_workflow,
    minimax_reference_duration_node,
    output_video_trim,
)
from lib.infra.ffmpeg import FfmpegUnavailableError, ffmpeg_executable, local_file_input
from lib.infra.media_probe import MediaProbeError, probe_media
from lib.infra.subprocess_deadline import SubprocessDeadlineExceeded, run_with_deadline

logger = logging.getLogger(__name__)

#: 本端点产出的是视频：产物扩展名白名单与失败文案共读这一个值
#: （见 ``comfyui.artifacts.ARTIFACT_SUFFIXES_BY_MEDIA_TYPE``）。
MEDIA_TYPE = "video"


class ComfyuiVideoBackend(ProviderJobIdPersistenceMixin):
    """把一份 ComfyUI 端点定义跑成一个分镜视频。"""

    def __init__(
        self,
        *,
        provider_id: str,
        model: str,
        base_url: str,
        api_key: str,
        definition: Mapping[str, Any],
        job_label: str | None = None,
        extra_base_urls: tuple[str, ...] = (),
    ) -> None:
        """``job_label`` 是非 worker 路径的任务标识，进上传文件名与 ``client_id``。

        worker 路径不传：那里有 ``request.task_id``，它才是这一笔在 剧灵 这一侧的身份。两者
        都没有时回落到一串随机 hex——在 ComfyUI 的队列界面上认不出是谁发的，但至少不会与别的
        调用方撞名。
        """
        self._provider = provider_id
        self._model = model
        self._definition = definition
        self._job_label = job_label
        self._nodes = comfyui_node_urls(base_url, extra_base_urls)
        self._base_url = base_url
        self._api_key = api_key
        self._client = ComfyuiClient(base_url=base_url, api_key=api_key, definition=definition)
        self._execution = ComfyuiExecution(client=self._client, definition=definition, media_type=MEDIA_TYPE)

    @property
    def name(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def video_capabilities(self) -> VideoCapabilities:
        """这份 workflow 的绑定表说它能做什么。

        这不是一份只在绕过工厂时才读的兜底声明：包装层的档位查询
        （``CustomVideoBackend.video_capabilities_for_tier``）刻意不短路回工厂注入的合成结果，而是
        以被包装 backend 的这份声明为基底再叠加用户覆盖。生成前的能力闸门走的正是那条路——这里
        少宣称一位，闸门就会在请求到达 :meth:`generate` 之前把它挡掉。
        """
        return binding_video_capabilities(self._definition)

    @property
    def accepts_previous_video(self) -> bool:
        return continuous_director_node(self._definition) is not None

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        continuous = is_continuous_h3(self._definition)
        if not continuous:
            url = await generation_node(self._provider, self._nodes, self._api_key, self._definition)
            if url is not None and url != self._client.base_url:
                return await self._bound_to(url).generate(request)
        count = len(request.reference_images or [])
        slots = derive_video_capabilities(self._definition).max_reference_images
        if count > slots:
            raise VideoCapabilityError("video_reference_images_exceeded", model=self._model, limit=slots, count=count)
        video_slots = len(_targets((self._definition.get("bindings") or {}).get("reference_videos")))
        video_count = len(request.reference_videos or [])
        neighbors = (request.previous_video, request.next_video)
        if any(neighbors) and not self.accepts_previous_video:
            raise ComfyuiError(EXECUTION_ERROR, node="LoadVideo", detail="该工作流不支持镜头衔接视频。")
        video_count += sum(path is not None for path in neighbors)
        if video_count > video_slots:
            raise VideoCapabilityError("video_reference_videos_exceeded", model=self._model, limit=video_slots, count=video_count)
        # 预检使用本地引用占位，不上传：无效绑定、欠填或缺失画幅必须在所有外部写入前失败。
        if (
            continuous
            or request.reference_audio_files
            or self._definition["bindings"].get("reference_audio")
            or self._definition["bindings"].get("aspect_ratio")
        ):
            preflight = await asyncio.to_thread(
                build_workflow,
                self._definition,
                prompt=request.prompt,
                aspect_ratio=request.aspect_ratio,
                resolution=request.resolution,
                duration_seconds=request.duration_seconds,
                media=MediaInputs(
                    start_image=str(request.start_image) if request.start_image else None,
                    end_image=str(request.end_image) if request.end_image else None,
                    reference_images=tuple(str(path) for path in request.reference_images or []),
                    reference_videos=tuple(str(path) for path in request.reference_videos or []),
                    previous_clip=(str(request.previous_video), 22) if request.previous_video else None,
                    next_clip=str(request.next_video) if request.next_video else None,
                    reference_audio_files=tuple(str(path) for path in request.reference_audio_files or []),
                ),
                seed=request.seed,
            )
        if continuous:
            if continuous_director_node(self._definition) is None:
                add_boundary_guides(preflight, self._definition["bindings"], seconds=4,
                                    before="before.mp4", after="after.mp4")
            return await run_continuous(self, request)
        job_label = request.task_id or self._job_label or uuid4().hex
        async with artifact_http_client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as http:
            media = await self._upload_media(http, request, job_label=job_label)
            built = await asyncio.to_thread(
                build_workflow,
                self._definition,
                prompt=request.prompt,
                aspect_ratio=request.aspect_ratio,
                # 时长原样转交：``frames`` 未绑定或读不到帧率时，构造层自己跳过帧数换算——在这里
                # 补一个缺省只会把「这份 workflow 的时长不由 剧灵 驱动」写成一个具体秒数。
                duration_seconds=request.duration_seconds,
                resolution=request.resolution,
                media=media,
                seed=request.seed,
            )
            prompt_id = await self._client.submit_prompt(
                http,
                built.workflow,
                client_id=client_id_for(job_label),
                record=lambda stage, body: notify_provider_response(request, stage, body),
            )
            await self._persist_provider_job_id(
                request, prompt_id, provider=self._provider, endpoint=self._client.base_url
            )
            picked = await self._execution.fetch_artifact(
                http,
                prompt_id,
                output_path=request.output_path,
                poll_timeout_seconds=request.poll_timeout_seconds,
                record=lambda stage, body: notify_provider_response(request, stage, body),
            )
            return await self._result(request, prompt_id, picked, built=built)

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        """接续一次已经提交过的执行：直接进轮询，既不重传素材也不重新提交 workflow。

        ``prompt_id`` 就是 ``provider_job_id``，而 ComfyUI 的执行完全在服务端，重新提交会在用户
        的显卡上把同一张图再跑一遍。``output`` 绑定读的是**当前**这份端点定义——用户在续跑之前改
        过绑定时，按新绑定去取产物是唯一说得通的口径，取不到即 ``comfyui_output_missing``。

        实发种子与 workflow 指纹不随续跑回来：两者只在提交那一次的构造里存在，而这条路不构造。

        域名取提交那一次的（``submitted_base_url``，由 resume_executor 从任务行回放），与声明式
        运行时同一口径：供应商的 base_url 可以在提交之后被改，而这一笔活在原来那台 ComfyUI 上。
        照当前域名去问，问的是另一台机器，它答「没有这个 prompt_id」——一次仍在出片的执行会被
        判成丢失，用户的显卡还在为它转。域名是连接维度，不是协议维度。
        """
        if job_id == CONTINUOUS_JOB_ID:
            if not is_continuous_h3(self._definition):
                raise ResumeExpiredError(job_id=job_id, provider=self._provider)
            return await run_continuous(self, request, resume=True)
        submitted = request.submitted_base_url
        if submitted and submitted != self._base_url:
            return await self._bound_to(submitted).resume_video(job_id, request)
        async with artifact_http_client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as http:
            picked = await self._execution.fetch_artifact(
                http,
                job_id,
                output_path=request.output_path,
                poll_timeout_seconds=request.poll_timeout_seconds,
                record=lambda stage, body: notify_provider_response(request, stage, body),
                # 续跑期的「执行找不着了」归 resume_expired：worker 据此标失败并结算那条 pending
                # 的调用行，而不是把它当成一次可以就地重试的生成失败。
                lost_error=lambda prompt_id: ResumeExpiredError(job_id=prompt_id, provider=self._provider),
            )
            return await self._result(request, job_id, picked, built=None)

    def _bound_to(self, base_url: str, *, api_key: str | None = None) -> ComfyuiVideoBackend:
        """同一份定义、换一个域名的另一个实例：轮询、取件与叫停这一路都得落在同一台机器上。"""
        return ComfyuiVideoBackend(
            provider_id=self._provider,
            model=self._model,
            base_url=base_url,
            api_key=self._api_key if api_key is None else api_key,
            definition=self._definition,
            job_label=self._job_label,
        )

    async def _result(
        self,
        request: VideoGenerationRequest,
        prompt_id: str,
        picked: PickedArtifact,
        *,
        built: BuiltWorkflow | None,
    ) -> VideoGenerationResult:
        """把取回的产物装成结果；``built`` 为 ``None`` 即这一笔是续跑（没有构造过）。"""
        warnings: tuple[Mapping[str, Any], ...] = ()
        if picked.count > 1:
            warnings = (
                {"key": "comfyui_multiple_outputs", "params": {"count": picked.count, "filename": picked.filename}},
            )
        workflow = built.workflow if built is not None else self._definition["workflow"]
        bindings = self._definition["bindings"]
        if (request.duration_seconds and output_video_trim(workflow, bindings) is None
                and minimax_reference_duration_node(workflow, bindings)):
            warning = await _align_minimax_duration(request.output_path, request.duration_seconds)
            if warning is not None:
                warnings += (warning,)
        return VideoGenerationResult(
            video_path=request.output_path,
            provider=self._provider,
            model=self._model,
            duration_seconds=request.duration_seconds,
            video_uri=self._execution.view_url(picked.artifact),
            task_id=prompt_id,
            # 实发种子与 workflow 指纹只在提交那一次的构造里存在：两者一起才说得清「这一版是照
            # 哪份图、用哪个种子出的」，而续跑这条路一样都没构造，故一起缺席而不是各给一个假值。
            seed=built.seed if built is not None else None,
            generate_audio=request.generate_audio,
            provenance={"workflow_sha256": built.workflow_sha256} if built is not None else None,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ 上传

    async def _upload_media(
        self, http: httpx.AsyncClient, request: VideoGenerationRequest, *, job_label: str
    ) -> MediaInputs:
        """上传绑定的首尾帧，以及已通过槽位容量校验的全部参考图。"""
        bindings: Mapping[str, Any] = self._definition.get("bindings") or {}
        start = await self._upload_one(http, request.start_image, bindings, "start_image", job_label=job_label)
        end = await self._upload_one(http, request.end_image, bindings, "end_image", job_label=job_label)
        references: list[str] = []
        for index, path in enumerate(request.reference_images or []):
            references.append(
                await self._client.upload_media(
                    http, path, filename=upload_filename(job_label, "reference_images", path, index)
                )
            )
        videos: list[str] = []
        for index, path in enumerate(request.reference_videos or []):
            videos.append(
                await self._client.upload_media(
                    http, path, filename=upload_filename(job_label, "reference_videos", path, index)
                )
            )
        audio = []
        for index, path in enumerate(request.reference_audio_files or []):
            audio.append(
                await self._client.upload_media(
                    http, path, filename=upload_filename(job_label, "reference_audio", path, index)
                )
            )
        previous_clip = None
        previous_clip_has_audio = False
        previous_clip_fps = None
        if request.previous_video is not None:
            previous = request.previous_video
            probe = await probe_media(previous)
            video = probe.first_stream("video")
            previous_clip_has_audio = request.generate_audio and probe.first_stream("audio") is not None
            if video is None or not video.packet_count:
                raise ComfyuiError(EXECUTION_ERROR, node="LoadVideo", detail="上一镜没有可用的视频帧。")
            if video.duration_seconds:
                previous_clip_fps = video.packet_count / video.duration_seconds
            uploaded = await self._client.upload_media(
                http, previous, filename=upload_filename(job_label, "previous_video", previous)
            )
            previous_clip = (uploaded, video.packet_count)
        next_clip = None
        next_clip_has_audio = False
        next_clip_fps = None
        next_clip_frames = None
        if request.next_video is not None:
            probe = await probe_media(request.next_video)
            video = probe.first_stream("video")
            if video is None or not video.packet_count:
                raise ComfyuiError(EXECUTION_ERROR, node="LoadVideo", detail="下一镜没有可用的视频帧。")
            next_clip_frames = video.packet_count
            next_clip_has_audio = request.generate_audio and probe.first_stream("audio") is not None
            if video.duration_seconds:
                next_clip_fps = video.packet_count / video.duration_seconds
            next_clip = await self._client.upload_media(
                http, request.next_video, filename=upload_filename(job_label, "next_video", request.next_video)
            )
        return MediaInputs(
            previous_clip=previous_clip,
            next_clip=next_clip,
            previous_clip_has_audio=previous_clip_has_audio,
            next_clip_has_audio=next_clip_has_audio,
            previous_clip_fps=previous_clip_fps,
            next_clip_fps=next_clip_fps,
            next_clip_frames=next_clip_frames,
            start_image=start,
            end_image=end,
            reference_images=tuple(references),
            reference_videos=tuple(videos),
            reference_audio_files=tuple(audio),
        )

    async def _upload_one(
        self,
        http: httpx.AsyncClient,
        path: Path | None,
        bindings: Mapping[str, Any],
        key: str,
        *,
        job_label: str,
    ) -> str | None:
        if path is None or not _targets(bindings.get(key)):
            return None
        return await self._client.upload_media(http, path, filename=upload_filename(job_label, key, path))


def _targets(raw: object) -> list[Mapping[str, Any]]:
    return [target for target in raw if isinstance(target, Mapping)] if isinstance(raw, list) else []


def binding_video_capabilities(definition: Mapping[str, Any]) -> VideoCapabilities:
    """把一份视频端点定义的绑定表装进 backend 层的能力类型。

    推导本身在 ``comfyui`` 子包里（它只认绑定表与 workflow）；装箱落在本模块，因为子包受
    「不依赖声明式运行时」的 forbidden 契约约束，够不到 ``VideoCapabilities``。端点投影
    （``endpoints.comfyui_endpoint_spec``）与 backend 自己的声明共用这一份，两处不各写一份——
    它们各自喂给能力闸门的不同一段，说的却必须是同一件事。

    参考音频段数只从绑定推导；总时长与 ``max_prompt_chars`` 没有依据，保持未声明。
    """
    bound = derive_video_capabilities(definition)
    return VideoCapabilities(
        text_to_video=bound.text_to_video,
        first_frame=bound.first_frame,
        last_frame=bound.last_frame,
        max_reference_images=bound.max_reference_images,
        audio_track=VideoAudioMode(bound.audio_track),
        reference_audio_mode=ReferenceAudioMode.DIRECT if bound.max_reference_audio_count else ReferenceAudioMode.NONE,
        max_reference_audio_count=bound.max_reference_audio_count,
    )


async def _align_minimax_duration(path: Path, seconds: int) -> Mapping[str, Any] | None:
    """Correct MiniMax's frame-grid rounding while preserving the complete scene and dialogue."""
    actual: float | None = None
    adjusted = path.with_name(f"{path.stem}.{uuid4().hex}.mp4")
    try:
        probe = await probe_media(path)
        actual = probe.duration_seconds
        video = probe.first_stream("video")
        if actual is None or video is None or not video.duration_seconds:
            raise MediaProbeError("视频时长不可用")
        rate = video.packet_count / video.duration_seconds
        tolerance = max(1 / rate, 0.025)
        audio = probe.first_stream("audio")
        drift = max(abs(stream.duration_seconds - seconds) for stream in (video, audio)
                    if stream is not None and stream.duration_seconds is not None)
        drift = max(drift, abs(actual - seconds))
        if drift <= tolerance:
            return None
        # MiniMax rounds up to the next 17k+5 frames. A larger mismatch needs a warning, not a speed change.
        if drift <= min(17 / rate, seconds * 0.2):
            args = [
                ffmpeg_executable(), "-hide_banner", "-nostdin", "-loglevel", "error", *local_file_input(path),
                "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", f"setpts={seconds / video.duration_seconds:.10f}*(PTS-STARTPTS),fps={rate:.8g},"
                       "tpad=stop_mode=clone:stop_duration=0.1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            ]
            if audio is not None and audio.duration_seconds:
                args += ["-af", f"atempo={audio.duration_seconds / seconds:.10f},apad", "-c:a", "aac"]
            args += ["-t", str(seconds), "-movflags", "+faststart", str(adjusted)]
            result = await run_with_deadline(args, deadline_seconds=60, capture_stderr=True)
            if result.returncode == 0:
                normalized = await probe_media(adjusted)
                if (
                    normalized.duration_seconds is not None
                    and abs(normalized.duration_seconds - seconds) <= tolerance
                    and normalized.first_stream("video") is not None
                    and (audio is None or normalized.first_stream("audio") is not None)
                    and all(
                        stream.duration_seconds is not None and abs(stream.duration_seconds - seconds) <= tolerance
                        for stream in normalized.streams
                    )
                ):
                    adjusted.replace(path)
                    return None
            logger.warning("MiniMax H3 视频时长校正失败：%s", result.stderr.decode(errors="replace")[-500:])
    except (FfmpegUnavailableError, MediaProbeError, OSError, SubprocessDeadlineExceeded) as exc:
        logger.warning("MiniMax H3 视频时长校正失败：%s", exc)
    finally:
        with suppress(OSError):
            adjusted.unlink(missing_ok=True)
    if actual is None:
        return {"key": "comfyui_video_duration_unavailable", "params": {"requested": seconds}}
    return {"key": "comfyui_video_duration_mismatch", "params": {"requested": seconds, "actual": round(actual, 3)}}
