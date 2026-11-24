"""用随包 ffmpeg 执行成片的渲染规划，并验收渲染结果。

画面按硬切边界分段渲染：段内每个片段按项目画布缩放补边、规整到固定帧率，取定帧数的源画面后用
边缘帧的静帧补足定格延长与转场借帧的余量缺口，非重叠型转场在片段两端淡入淡出，重叠型转场用
``xfade`` 在切点窗口内交叉过渡；烧入字幕时各段把画面时间平移回成片时间，交给 libass 按整集的 ASS 文档
渲染。各段用同一组编码参数输出，最后以 ``-c copy`` 无损拼接。音频不分段：整集原声按片段音量与帧边界、
旁白配音（仅带旁白版本）按承载片段的起点、BGM 按片段起点以响度增益乘片段音量并做淡入淡出，一次混音、
一次编码，再与拼好的画面封装，避免各段 AAC 编码的前置填充在段边界产生缝隙与累积偏差。各路相加后先过限幅器，
高增益 BGM 与原声、旁白叠加也不越过满幅。旁白越界如实渲染：
重叠处同时响起，超出末尾的部分随成片截止。
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from lib.final_cut.errors import FinalCutError
from lib.final_cut.render_plan import PlannedClip, RenderPlan, RenderSegment
from lib.final_cut.subtitles import BurnedSubtitle, ass_document
from lib.edit_timeline.model import ClipAudioProcessing, ClipGrade, GainKeyframe
from lib.infra.async_thread import run_sync_transaction
from lib.infra.ffmpeg import local_file_input
from lib.infra.media_probe import MediaProbeError, probe_media
from lib.infra.subprocess_deadline import (
    DEFAULT_TERMINATE_GRACE_SECONDS,
    Spawner,
    SubprocessDeadlineExceeded,
    run_with_deadline,
)
from lib.subtitle_style.font import SUBTITLE_FONT_FILE

AUDIO_SAMPLE_RATE = 48_000

MIX_LIMIT = 0.891251
"""混音限幅器的上限（线性幅度，约 −1 dBFS），给 AAC 编码的峰值过冲留出余量。"""

ACCEPTANCE_TOLERANCE_SECONDS = 0.1
"""验收时音视频流时长与剪辑时间线时长之间允许的最大偏差。"""

SUBTITLE_DOCUMENT = "subtitles.ass"
SUBTITLE_FONTS_DIR = "fonts"
"""烧入字幕时 ASS 文档与字体在工作目录里的相对路径；画面渲染以工作目录为当前目录，滤镜参数不必转义路径。"""

_STDERR_TAIL = 2000


@dataclass(frozen=True, slots=True)
class RenderDeadlines:
    """各步 ffmpeg 子进程的 deadline：固定下限加按时长放大的余量（秒）。"""

    floor: float = 120.0
    per_output_second: float = 20.0
    grace: float = DEFAULT_TERMINATE_GRACE_SECONDS

    def for_seconds(self, seconds: float) -> float:
        return self.floor + self.per_output_second * seconds


DEFAULT_RENDER_DEADLINES = RenderDeadlines()


def _base_args(ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y"]


def _seconds(microseconds: int) -> str:
    return f"{microseconds / 1_000_000:.6f}"


def _frames_seconds(frames: int, fps: int) -> str:
    return f"{frames / fps:.6f}"


def grade_filters(grade: ClipGrade) -> list[str]:
    if not grade.exposure and grade.temperature == 6500:
        return []
    filters = ["format=gbrp"]
    if grade.exposure:
        filters.append(f"exposure=exposure={grade.exposure:.6f}")
    if grade.temperature != 6500:
        filters.append(f"colortemperature=temperature={grade.temperature}")
    return [*filters, "format=yuv420p"]


def source_audio_filters(processing: ClipAudioProcessing | None) -> list[str]:
    if processing is None:
        return []
    filters = []
    if processing.denoise_db:
        filters.append(f"afftdn=nr={max(0.01, processing.denoise_db):.4f}:tn=1")
    if processing.compression_ratio > 1:
        filters.append(f"acompressor=threshold=0.125:ratio={processing.compression_ratio:.4f}:attack=10:release=100")
    return filters


def _clip_chain(index: int, planned: PlannedClip, plan: RenderPlan) -> str:
    """一个片段的画面滤镜链：规整画布与帧率，截出所需源画面，两端用边缘帧定格补齐，再加淡入淡出。"""
    profile = plan.profile
    width, height = profile.width, profile.height
    source_frames = planned.lead.source_frames + planned.source_frames + planned.trail.source_frames
    filters = [
        f"fps={profile.fps}",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
        "format=yuv420p",
        f"trim=end_frame={max(source_frames, 1)}",
        f"tpad=start_mode=clone:start={planned.lead.freeze_frames}:stop_mode=clone:stop=-1",
        # tpad 的输出不声明帧率，xfade 要求输入是恒定帧率；在无尽的补帧流上重新声明，再按帧数截止。
        f"fps={profile.fps}",
        f"trim=end_frame={planned.stream_frames}",
    ]
    prefix = f"[{index}:v:0]"
    if planned.clip.grade is not None and (correction := grade_filters(planned.clip.grade)):
        if ramp := planned.clip.grade.fade_to_neutral_us:
            prefix += ",".join(filters) + f",setpts=PTS-STARTPTS,split=2[base{index}][color{index}];"
            prefix += f"[color{index}]{','.join(correction)}[graded{index}];[graded{index}][base{index}]"
            ratio = f"clip(T/{_seconds(ramp)},0,1)"
            filters = [f"blend=all_expr='A*(1-{ratio})+B*{ratio}'"]
        else:
            filters.extend(correction)
    if planned.fade_in is not None:
        filters.append(f"fade=t=in:s=0:n={planned.fade_in.frames}:c={planned.fade_in.color}")
    if planned.fade_out is not None:
        start = planned.stream_frames - planned.fade_out.frames
        filters.append(f"fade=t=out:s={start}:n={planned.fade_out.frames}:c={planned.fade_out.color}")
    return f"{prefix}{','.join(filters)}[v{index}]"


@dataclass(frozen=True, slots=True)
class NarrationInput:
    """混进整集音频的一段旁白配音：从成片时间 ``start_us`` 起整段播放。"""

    path: Path
    start_us: int
    source_in_us: int = 0
    duration_us: int | None = None


@dataclass(frozen=True, slots=True)
class BgmInput:
    """混进整集音频的一段 BGM：从 BGM 的 ``source_in_us`` 起取 ``duration_us``，放在成片时间 ``start_us``。

    ``volume`` 已是响度增益乘以片段音量；淡入淡出以微秒计，0 表示不做。
    """

    path: Path
    start_us: int
    source_in_us: int
    duration_us: int
    volume: float
    fade_in_us: int
    fade_out_us: int
    gain_envelope: tuple[GainKeyframe, ...] = ()
    processing: ClipAudioProcessing | None = None


def _envelope_expression(points: Sequence[GainKeyframe]) -> str:
    """Interpolate gain in dB and clamp before the first and after the last keyframe."""
    if len(points) == 1:
        return f"{points[0].db:g}"
    if len(points) == 2:
        a, b = points
        return f"{a.db:g}+({b.db - a.db:g})*clip((t-{_seconds(a.time_us)})/{_seconds(b.time_us - a.time_us)},0,1)"
    mid = len(points) // 2
    return f"if(lt(t,{_seconds(points[mid].time_us)}),{_envelope_expression(points[:mid+1])},{_envelope_expression(points[mid:])})"


def _bgm_chain(index: int, bgm: BgmInput, start_sample: int) -> str:
    filters = [
        f"aresample={AUDIO_SAMPLE_RATE}",
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
        *source_audio_filters(bgm.processing),
        f"atrim=end_sample={bgm.duration_us * AUDIO_SAMPLE_RATE // 1_000_000}",
        "asetpts=PTS-STARTPTS",
        f"volume={bgm.volume:.6f}",
    ]
    if bgm.gain_envelope:
        filters.append(f"volume='pow(10,({_envelope_expression(bgm.gain_envelope)})/20)':eval=frame")
    if bgm.fade_in_us > 0:
        filters.append(f"afade=t=in:st=0:d={_seconds(bgm.fade_in_us)}")
    if bgm.fade_out_us > 0:
        filters.append(f"afade=t=out:st={_seconds(bgm.duration_us - bgm.fade_out_us)}:d={_seconds(bgm.fade_out_us)}")
    filters.append(f"adelay=delays={start_sample}S:all=1")
    return f"[{index}:a:0]{','.join(filters)}[a{index}]"


def segment_args(
    ffmpeg: str, segment: RenderSegment, plan: RenderPlan, output: Path, *, burn_subtitles: bool = False
) -> list[str]:
    """一段片段的画面渲染参数：只含画面，按帧数精确截止。

    ``burn_subtitles`` 时按相对路径引用工作目录里的 ASS 文档与字体，须以工作目录为当前目录运行。
    """
    fps = plan.profile.fps
    inputs: list[str] = []
    chains: list[str] = []
    for index, planned in enumerate(segment.clips):
        lead_us = planned.lead.source_frames * 1_000_000 // fps
        inputs += [
            "-ss",
            _seconds(max(planned.clip.source_in_us - lead_us, 0)),
            *local_file_input(planned.clip.video_path),
        ]
        chains.append(_clip_chain(index, planned, plan))
    label = "[v0]"
    for index, crossfade in enumerate(segment.crossfades, start=1):
        joined = f"[x{index}]"
        chains.append(
            f"{label}[v{index}]xfade=transition={crossfade.effect}:duration={_frames_seconds(crossfade.frames, fps)}"
            f":offset={_frames_seconds(crossfade.offset_frames, fps)}{joined}"
        )
        label = joined
    if burn_subtitles:
        # libass 按画面时间取字幕：先把段内时间平移到成片时间，烧入后再移回段内时间。
        offset = _frames_seconds(segment.start_frame, fps)
        chains.append(
            f"{label}setpts=PTS+{offset}/TB,subtitles=f={SUBTITLE_DOCUMENT}:fontsdir={SUBTITLE_FONTS_DIR},"
            "setpts=PTS-STARTPTS[subtitled]"
        )
        label = "[subtitled]"
    return [
        *_base_args(ffmpeg),
        *inputs,
        "-filter_complex",
        ";".join(chains),
        "-map",
        label,
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        str(segment.frames),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-f",
        "mp4",
        str(output),
    ]


def _samples(frames: int, fps: int) -> int:
    return frames * AUDIO_SAMPLE_RATE // fps


def _audible(planned: PlannedClip) -> bool:
    return planned.clip.has_audio and planned.clip.source_volume > 0 and planned.source_frames > 0


@dataclass(slots=True)
class _SourceAudioEdges:
    lead: int = 0
    trail: int = 0
    fade_in: int = 0
    fade_out: int = 0


def _source_audio_edges(plan: RenderPlan) -> list[_SourceAudioEdges]:
    clips = plan.clips
    edges = [_SourceAudioEdges() for _ in clips]
    fps = plan.profile.fps
    for index, (left, right) in enumerate(pairwise(clips)):
        frames = left.clip.audio_overlap_frames
        if not frames:
            continue
        outgoing, incoming = edges[index], edges[index + 1]
        left_room = left.source_frames // 2 if _audible(left) else 0
        right_room = right.source_frames // 2 if _audible(right) else 0
        if left_room and right_room and not left.hold_frames:
            audio_end = left.clip.audio_duration_us or left.clip.media_duration_us
            head = right.clip.source_in_us * fps // 1_000_000
            tail = max(0, audio_end - left.clip.source_out_us) * fps // 1_000_000
            before_limit, after_limit = min(left_room, head), min(right_room, tail)
            before = min(before_limit, frames // 2)
            after = min(after_limit, frames - before)
            before = min(before_limit, frames - after)
            if before or after:
                outgoing.trail, incoming.lead = after, before
                outgoing.fade_out = incoming.fade_in = before + after
                continue
        # 没有可借的素材时，在切点两侧用短淡出和淡入软化边界。
        half = max(1, frames // 2)
        outgoing.fade_out = min(left_room, half)
        incoming.fade_in = min(right_room, half)
    return edges


def audio_mix_args(
    ffmpeg: str,
    plan: RenderPlan,
    output: Path,
    *,
    narrations: Sequence[NarrationInput] = (),
    bgm: Sequence[BgmInput] = (),
) -> list[str]:
    """整集混音参数：以静音垫底，每个有声片段按帧边界落位、按原声音量缩放；旁白配音从起点所在的帧边界起
    原音量叠加；BGM 从起点所在的帧边界起按增益与音量叠加并淡入淡出，相加后限幅，整体截到成片时长。"""
    fps = plan.profile.fps
    total_samples = _samples(plan.total_frames, fps)
    inputs: list[str] = ["-f", "lavfi", "-i", f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl=stereo"]
    chains = [f"[0:a]atrim=end_sample={total_samples}[base]"]
    labels = ["[base]"]
    for planned, edge in zip(plan.clips, _source_audio_edges(plan), strict=True):
        if not _audible(planned):
            continue
        index = len(labels)
        source_in = max(0, planned.clip.source_in_us - round(edge.lead * 1_000_000 / fps))
        inputs += ["-ss", _seconds(source_in), *local_file_input(planned.clip.video_path)]
        start = _samples(planned.start_frame - edge.lead, fps)
        length = _samples(planned.source_frames + edge.lead + edge.trail, fps)
        chain = [
            f"[{index}:a:0]aresample={AUDIO_SAMPLE_RATE}",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
        ]
        chain.extend(source_audio_filters(planned.clip.audio_processing))
        if edge.fade_in or edge.fade_out:
            chain.append(f"apad=whole_len={length}")
        chain.extend((f"atrim=end_sample={length}", "asetpts=PTS-STARTPTS", f"volume={planned.clip.source_volume:.4f}"))
        if edge.fade_in:
            chain.append(f"afade=t=in:ss=0:ns={_samples(edge.fade_in, fps)}")
        if edge.fade_out:
            fade = _samples(edge.fade_out, fps)
            chain.append(f"afade=t=out:ss={length - fade}:ns={fade}")
        chain.append(f"adelay=delays={start}S:all=1[a{index}]")
        chains.append(",".join(chain))
        labels.append(f"[a{index}]")
    for narration in narrations:
        index = len(labels)
        if narration.source_in_us:
            inputs += ["-ss", _seconds(narration.source_in_us)]
        inputs += local_file_input(narration.path)
        start = _samples(plan.profile.frame_at(narration.start_us), fps)
        trim = (f"atrim=end_sample={narration.duration_us * AUDIO_SAMPLE_RATE // 1_000_000},"
                if narration.duration_us is not None else "")
        chains.append(
            f"[{index}:a:0]aresample={AUDIO_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"{trim}asetpts=PTS-STARTPTS,adelay=delays={start}S:all=1[a{index}]"
        )
        labels.append(f"[a{index}]")
    for item in bgm:
        index = len(labels)
        inputs += ["-ss", _seconds(item.source_in_us), *local_file_input(item.path)]
        chains.append(_bgm_chain(index, item, _samples(plan.profile.frame_at(item.start_us), fps)))
        labels.append(f"[a{index}]")
    if len(labels) == 1:
        chains = [f"[0:a]atrim=end_sample={total_samples}[mix]"]
    else:
        chains.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0:dropout_transition=0,"
            # 只压超限的峰：关闭自动电平，补偿前视延迟以免整条音轨后移。
            f"alimiter=limit={MIX_LIMIT}:level=false:latency=true,"
            f"atrim=end_sample={total_samples}[mix]"
        )
    return [
        *_base_args(ffmpeg),
        *inputs,
        "-filter_complex",
        ";".join(chains),
        "-map",
        "[mix]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-f",
        "mp4",
        str(output),
    ]


def mux_args(ffmpeg: str, concat_list: Path, audio: Path, output: Path) -> list[str]:
    """把各段画面无损拼接，并与整集混音封装成成片。"""
    return [
        *_base_args(ffmpeg),
        "-f",
        "concat",
        "-safe",
        "0",
        *local_file_input(concat_list),
        *local_file_input(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(output),
    ]


async def _run(
    args: list[str], *, deadline: float, grace: float, spawn: Spawner | None, output: Path, cwd: Path | None = None
) -> None:
    try:
        result = await run_with_deadline(
            args,
            deadline_seconds=deadline,
            grace=grace,
            capture_stderr=True,
            cleanup_paths=(output,),
            spawn=spawn,
            cwd=cwd,
        )
    except SubprocessDeadlineExceeded:
        raise FinalCutError("final_cut_render_failed", f"ffmpeg 渲染超时：{output.name}") from None
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()[-_STDERR_TAIL:]
        raise FinalCutError(
            "final_cut_render_failed",
            f"ffmpeg 渲染失败（退出码 {result.returncode}）：{stderr}",
            returncode=result.returncode,
        )


async def render_plan_to_file(
    ffmpeg: str,
    plan: RenderPlan,
    output: Path,
    workspace: Path,
    *,
    narrations: Sequence[NarrationInput] = (),
    bgm: Sequence[BgmInput] = (),
    subtitles: Sequence[BurnedSubtitle] | None = None,
    deadlines: RenderDeadlines = DEFAULT_RENDER_DEADLINES,
    spawn: Spawner | None = None,
) -> None:
    """执行渲染规划：逐段渲染画面、整集混音，再拼接封装到 ``output``；中间文件只写在 ``workspace``。

    ``subtitles`` 不为 None 时烧入字幕（可以为空），``narrations`` 与 ``bgm`` 是要混进整集音频的旁白配音与 BGM。
    """
    fps = plan.profile.fps
    burn = subtitles is not None
    if subtitles is not None:
        await run_sync_transaction(_stage_subtitles, workspace, ass_document(subtitles, plan.profile))
    segment_files: list[Path] = []
    for index, segment in enumerate(plan.segments):
        segment_file = workspace / f"segment_{index:04d}.mp4"
        await _run(
            segment_args(ffmpeg, segment, plan, segment_file, burn_subtitles=burn),
            deadline=deadlines.for_seconds(segment.frames / fps),
            grace=deadlines.grace,
            spawn=spawn,
            output=segment_file,
            cwd=workspace if burn else None,
        )
        segment_files.append(segment_file)
    audio_file = workspace / "audio.m4a"
    mix_args = audio_mix_args(ffmpeg, plan, audio_file, narrations=narrations, bgm=bgm)
    # Long gain envelopes can exceed the Windows command line limit.
    if any(item.gain_envelope for item in bgm):
        graph = mix_args.index("-filter_complex")
        graph_file = workspace / "mix.ffgraph"
        await run_sync_transaction(graph_file.write_text, mix_args[graph + 1], encoding="utf-8")
        mix_args[graph:graph + 2] = ["-/filter_complex", str(graph_file)]
    await _run(
        mix_args,
        deadline=deadlines.for_seconds(plan.duration_seconds),
        grace=deadlines.grace,
        spawn=spawn,
        output=audio_file,
    )
    concat_list = workspace / "segments.txt"
    await run_sync_transaction(
        concat_list.write_text, "".join(f"file '{path.name}'\n" for path in segment_files), encoding="utf-8"
    )
    await _run(
        mux_args(ffmpeg, concat_list, audio_file, output),
        deadline=deadlines.for_seconds(plan.duration_seconds / 10),
        grace=deadlines.grace,
        spawn=spawn,
        output=output,
    )


def _stage_subtitles(workspace: Path, document: str) -> None:
    """把 ASS 文档与随包字体放进工作目录；字体优先硬链接，跨卷时复制。"""
    (workspace / SUBTITLE_DOCUMENT).write_text(document, encoding="utf-8")
    fonts = workspace / SUBTITLE_FONTS_DIR
    fonts.mkdir(exist_ok=True)
    target = fonts / SUBTITLE_FONT_FILE.name
    try:
        target.hardlink_to(SUBTITLE_FONT_FILE)
    except OSError:
        shutil.copyfile(SUBTITLE_FONT_FILE, target)


@dataclass(frozen=True, slots=True)
class FinalCutAcceptance:
    """成片验收结果：剪辑时间线应有的时长与实测的音视频流时长（秒）。"""

    expected_duration: float
    video_duration: float
    audio_duration: float
    tolerance: float = ACCEPTANCE_TOLERANCE_SECONDS


async def accept_final_cut(path: Path, plan: RenderPlan, *, spawn: Spawner | None = None) -> FinalCutAcceptance:
    """经媒体探测接口验收成片：音视频流齐全，两者时长都与剪辑时间线时长相差不超过容差。"""
    try:
        probe = await probe_media(path, spawn=spawn)
    except MediaProbeError as exc:
        raise FinalCutError("final_cut_acceptance_failed", f"成片无法探测：{exc}") from exc
    video = probe.first_stream("video")
    audio = probe.first_stream("audio")
    if video is None or video.duration_seconds is None or audio is None or audio.duration_seconds is None:
        raise FinalCutError(
            "final_cut_acceptance_failed",
            "成片缺少视频流或音频流",
            has_video=video is not None,
            has_audio=audio is not None,
        )
    acceptance = FinalCutAcceptance(
        expected_duration=round(plan.duration_seconds, 3),
        video_duration=round(video.duration_seconds, 3),
        audio_duration=round(audio.duration_seconds, 3),
    )
    worst = max(
        abs(video.duration_seconds - plan.duration_seconds), abs(audio.duration_seconds - plan.duration_seconds)
    )
    if worst > ACCEPTANCE_TOLERANCE_SECONDS:
        raise FinalCutError(
            "final_cut_acceptance_failed",
            f"成片时长偏差超出容差：应为 {acceptance.expected_duration} 秒，"
            f"视频 {acceptance.video_duration} 秒、音频 {acceptance.audio_duration} 秒",
            expected_duration=acceptance.expected_duration,
            video_duration=acceptance.video_duration,
            audio_duration=acceptance.audio_duration,
        )
    return acceptance


__all__ = [
    "ACCEPTANCE_TOLERANCE_SECONDS",
    "AUDIO_SAMPLE_RATE",
    "DEFAULT_RENDER_DEADLINES",
    "BgmInput",
    "FinalCutAcceptance",
    "NarrationInput",
    "RenderDeadlines",
    "accept_final_cut",
    "audio_mix_args",
    "mux_args",
    "render_plan_to_file",
    "segment_args",
]
