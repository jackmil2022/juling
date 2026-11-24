"""Frame-exact stitching for adjacent H3 clips, preserving every planned source frame."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from lib.infra.ffmpeg import ffmpeg_executable, local_file_input
from lib.infra.media_probe import probe_media, probe_video_frame_times
from lib.infra.subprocess_deadline import run_with_deadline

FPS = 24


@dataclass(frozen=True)
class StitchPart:
    path: Path
    frames: int | None = None
    trim_head: int = 0
    trim_tail: int = 0


async def stitch_clips(parts: list[StitchPart], output: Path, *, audio: bool) -> list[int]:
    if not parts:
        raise ValueError("No video clips to stitch")
    probes = await asyncio.gather(*(probe_media(part.path) for part in parts))
    first = probes[0].first_stream("video")
    if first is None or first.dimensions is None:
        raise ValueError("First clip has no usable video dimensions")
    width, height = (size + size % 2 for size in first.dimensions)
    fit = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
    args = [ffmpeg_executable(), "-hide_banner", "-nostdin", "-loglevel", "error", "-xerror", "-y"]
    filters, ordered, tracks = [], [], []
    kept_frames = []
    for index, (part, probe) in enumerate(zip(parts, probes, strict=True)):
        video = probe.first_stream("video")
        if video is None or video.dimensions is None:
            raise ValueError(f"Clip {index + 1} has no usable video frames")
        times = await probe_video_frame_times(part.path, decode=bool(part.trim_head or part.trim_tail))
        start = part.trim_head
        end = len(times) - part.trim_tail if part.frames is None else start + part.frames
        if not 0 <= start < end <= len(times) - part.trim_tail:
            raise ValueError(f"第 {index + 1} 段视频共 {len(times)} 帧，无法保留帧区间 [{start}, {end})。")
        if any(abs(time - frame / FPS) > 0.001 for frame, time in enumerate(times[:end])):
            raise ValueError(f"第 {index + 1} 段视频帧率与工作流的 {FPS} fps 不符。")
        frames = end - start
        kept_frames.append(frames)
        args.extend(local_file_input(part.path))
        normalize = "setsar=1,format=yuv420p" if video.dimensions == (width, height) else fit
        filters.append(
            f"[{index}:v]trim=start_frame={start}:end_frame={end},settb=1/{FPS},setpts=N,{normalize}[keep{index}]"
        )
        ordered.append(f"[keep{index}]")
        if audio:
            sound = probe.first_stream("audio")
            if sound and sound.duration_seconds:
                track = f"[{index}:a]aresample=48000:first_pts=0,aformat=channel_layouts=stereo,apad"
            else:
                track = "anullsrc=r=48000:cl=stereo"
            track += (f",atrim=start_sample={start * 48000 // FPS}:end_sample={end * 48000 // FPS},"
                      "asetpts=PTS-STARTPTS")
            if index:
                track += ",afade=t=in:d=0.012"
            if index + 1 < len(parts):
                track += f",afade=t=out:st={max(0, frames / FPS - 0.012):.6f}:d=0.012"
            tracks.append(f"[audio{index}]")
            filters.append(track + tracks[-1])
    # Rebuild timestamps from frame indexes: concat can round timestamps or reuse them at a one-frame join.
    filters.append("".join(ordered) + f"concat=n={len(ordered)}:v=1:a=0,settb=1/{FPS},setpts=N[outv]")
    total_frames = sum(kept_frames)
    args += ["-filter_complex_threads", "2", "-filter_complex", ";".join(filters + (
        ["".join(tracks) + f"concat=n={len(tracks)}:v=0:a=1[outa]"] if audio else []
    )), "-map", "[outv]", "-r", str(FPS), "-fps_mode:v", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "2"]
    if audio:
        args += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    temporary = output.with_name(f"{output.stem}.joining.mp4")
    try:
        result = await run_with_deadline(
            args + ["-movflags", "+faststart", str(temporary)],
            deadline_seconds=max(60, total_frames / FPS * 8),
            capture_stderr=True,
            cleanup_paths=[temporary],
        )
        if result.returncode:
            raise ValueError(result.stderr.decode(errors="replace")[-1400:])
        validated = await probe_media(temporary)
        stream = validated.first_stream("video")
        if not stream or stream.packet_count != total_frames:
            raise ValueError("Stitched video does not match the planned frame count")
        temporary.replace(output)
        return kept_frames
    finally:
        temporary.unlink(missing_ok=True)
