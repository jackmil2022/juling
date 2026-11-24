"""Create the audio/video excerpts used for continuity references."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Literal

from lib.infra.content_digest import sha256_file_with_size
from lib.infra.ffmpeg import ffmpeg_executable, local_file_input
from lib.infra.media_probe import probe_media, probe_video_frame_times
from lib.infra.subprocess_deadline import run_with_deadline


async def continuity_clip(source: Path, cache_dir: Path, role: Literal["previous_video", "next_video"]) -> tuple[Path, str]:
    digest, size = await asyncio.to_thread(sha256_file_with_size, source)
    await asyncio.to_thread(cache_dir.mkdir, parents=True, exist_ok=True)
    destination = cache_dir / f"v1-{digest}-{role}.mp4"
    if destination.is_file():
        return destination, digest

    times = await probe_video_frame_times(source, decode=True)
    probe = await probe_media(source)
    video = probe.first_stream("video")
    if video is None:
        raise ValueError(f"参考视频没有视频流：{source.name}")
    start_frame = max(0, len(times) - 22) if role == "previous_video" else 0
    end_frame = len(times) if role == "previous_video" else min(5, len(times))
    start = times[start_frame]
    if end_frame < len(times):
        end = times[end_frame]
    else:
        frame_duration = times[-1] - times[-2] if len(times) > 1 else (video.duration_seconds or 1 / 25)
        end = times[-1] + max(frame_duration, 1 / 1000)
    fd, temporary_name = tempfile.mkstemp(prefix=".continuity-", suffix=".mp4", dir=cache_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        args = [ffmpeg_executable(), "-hide_banner", "-nostdin", "-v", "error", "-y", *local_file_input(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf",
                f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=PTS-STARTPTS",
                "-af", f"atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS",
                "-fps_mode:v", "passthrough", "-enc_time_base:v", "filter", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-bf", "0", "-c:a", "aac", "-use_editlist", "0", "-movflags", "+faststart", str(temporary)]
        result = await run_with_deadline(args, deadline_seconds=120, capture_stderr=True, cleanup_paths=[temporary])
        if result.returncode:
            raise ValueError(f"参考视频裁剪失败：{source.name}：{result.stderr.decode(errors='replace')[-1000:]}")
        if await asyncio.to_thread(sha256_file_with_size, source) != (digest, size):
            raise ValueError(f"参考视频裁剪期间发生变化：{source.name}")
        await asyncio.to_thread(os.replace, temporary, destination)
        return destination, digest
    finally:
        temporary.unlink(missing_ok=True)
