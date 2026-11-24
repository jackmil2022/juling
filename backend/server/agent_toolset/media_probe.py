"""只读探测会话项目的本地音视频。"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lib.infra.ffmpeg import FfmpegUnavailableError
from lib.infra.media_probe import MediaProbeError, probe_media
from lib.infra.path_safety import try_safe_join
from server.agent_toolset.declaration import Exempt, ToolDeclaration
from server.media_tools.context import tool_problem
from server.tool_runtime import CallerContext, ProjectScope, Services, ToolOutcome, ToolRequest

# 显式指定 demuxer，防止伪装成音视频的播放列表引用其他文件。
_INPUT_FORMATS = {
    ".mp4": "mov",
    ".mov": "mov",
    ".m4v": "mov",
    ".m4a": "mov",
    ".webm": "matroska",
    ".mkv": "matroska",
    ".mp3": "mp3",
    ".wav": "wav",
    ".flac": "flac",
    ".aac": "aac",
    ".ogg": "ogg",
    ".opus": "ogg",
}


class ProbeProjectMediaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, description="项目内现有音视频文件的相对路径，如 videos/clip.mp4。")


async def probe_project_media(
    request: ToolRequest[ProbeProjectMediaRequest],
    scope: ProjectScope,
    _caller: CallerContext,
    services: Services,
) -> ToolOutcome[dict[str, Any]]:
    relative = request.value.path.replace("\\", "/")
    if relative.startswith("/") or ":" in relative or ".." in relative.split("/"):
        return tool_problem("请提供当前项目内的媒体文件相对路径。", code="unsafe_path")

    root = services.projects.get_project_path(scope.project_name)
    media = await asyncio.to_thread(try_safe_join, root, relative, require_file=True)
    if media is None:
        return tool_problem("媒体文件不存在或超出当前项目范围。", code="file_not_found")
    input_format = _INPUT_FORMATS.get(media.suffix.lower())
    if input_format is None:
        return tool_problem("该文件类型不支持媒体探测。", code="unsupported_media_type")

    try:
        result = await probe_media(media, input_format=input_format)
    except FfmpegUnavailableError:
        return tool_problem("随包 ffmpeg 不可用。", code="ffmpeg_unavailable")
    except MediaProbeError as exc:
        return tool_problem(str(exc), code="media_unreadable")
    except OSError:
        return tool_problem("无法启动 ffmpeg 或读取媒体文件。", code="media_unreadable")
    return ToolOutcome(value={
        "path": relative,
        "container_formats": sorted(result.container_formats),
        "duration_seconds": result.duration_seconds,
        "streams": result.streams,
    })


PROBE_PROJECT_MEDIA = ToolDeclaration(
    name="probe_project_media",
    description=(
        "只读探测当前项目的本地音视频文件。检查有无音轨、编码、时长或视频尺寸时，直接调用本工具。"
        "使用已知的项目相对路径，返回容器格式、总时长和每条音视频流的技术参数。"
    ),
    request_model=ProbeProjectMediaRequest,
    migration=Exempt("按路径读取媒体文件，无需读取产物清单或签发写入凭据。"),
    domain_key="project_media",
    handler=probe_project_media,
)
