from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import stat
import subprocess
import tempfile
import wave
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

from lib.edit_timeline.model import StemKind
from lib.infra.ffmpeg import FfmpegUnavailableError, ffmpeg_executable, local_file_input
from lib.material.work_files import hold_work_file

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)
_MODEL_DIR = Path(__file__).resolve().parents[3] / "third_party" / "rnnoise"
_PEAKS_PER_SECOND = 100
_RATE = 48_000
# RNNoise's overlap-add introduces one 480-sample frame of delay.
_SPLIT = (
    "[0:a:0]aresample=48000:first_pts=0,aformat=channel_layouts=stereo,asplit[dry][input];"
    "[input]apad=pad_len=480,arnndn=m=std.rnnn,atrim=start_sample=480,asetpts=N/SR/TB[voice];"
    "[dry][voice]join=inputs=2:channel_layout=quad:map=0.0-FL|0.1-FR|1.0-BL|1.1-BR[out]"
)
_JOBS: dict[Path, asyncio.Task["AudioAnalysis"]] = {}
_LIMIT = asyncio.Semaphore(4)


class AudioStem(TypedDict):
    kind: StemKind
    peaks: str


class AudioAnalysis(TypedDict):
    key: str
    peaks: str
    peaks_per_second: int
    stems: list[AudioStem]


def _peaks(samples: np.ndarray, rate: int) -> bytes:
    import numpy as np

    block = rate // _PEAKS_PER_SECOND
    frames = np.abs(samples)
    if tail := len(frames) % block:
        frames = np.pad(frames, ((0, block - tail), (0, 0)))
    amplitude = frames.reshape(-1, block * 2).max(axis=1)
    # Keep quiet sounds readable without drawing bars over digital silence.
    amplitude[amplitude < 0.00032] = 0
    return np.rint(np.sqrt(np.minimum(amplitude, 1)) * 255).astype(np.uint8).tobytes()


def _write_wave(audio: wave.Wave_write, samples: np.ndarray) -> None:
    import numpy as np

    pcm = np.rint(np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2")
    audio.writeframesraw(memoryview(pcm).cast("B"))


def _encode_peaks(peaks: bytearray) -> str:
    return base64.b64encode(peaks).decode() if any(peaks) else ""


def _analyse(
    source: Path, target: Path, split: bool, info: os.stat_result
) -> AudioAnalysis:
    metadata = target / "peaks.json"
    if metadata.is_file():
        return json.loads(metadata.read_bytes())
    import numpy as np

    rate = _RATE if split else 12_000
    channels = 4 if split else 2
    command = [
        ffmpeg_executable(),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "1",
    ]
    command.extend(local_file_input(source))
    if split:
        command.extend(
            ["-filter_complex_threads", "2", "-filter_complex", _SPLIT, "-map", "[out]"]
        )
    else:
        command.extend(["-map", "0:a:0", "-ac", "2"])
    command.extend(["-ar", str(rate), "-f", "f32le", "pipe:1"])
    data: AudioAnalysis = {
        "key": target.name,
        "peaks": "",
        "peaks_per_second": _PEAKS_PER_SECOND,
        "stems": [],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=target.parent) as staging,
        tempfile.TemporaryFile(dir=target.parent) as raw,
    ):
        with hold_work_file(source):
            result = subprocess.run(
                command,
                cwd=_MODEL_DIR,
                stdout=raw,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            current = source.stat()
        if (current.st_mtime_ns, current.st_size) != (info.st_mtime_ns, info.st_size):
            raise ValueError("Source changed during audio analysis")
        if result.returncode:
            logger.warning(
                "Timeline audio analysis failed: %s",
                result.stderr.decode(errors="replace").strip(),
            )
            raise ValueError("Audio analysis failed")
        directory = Path(staging)
        raw.seek(0)
        if split:
            stems: tuple[Literal["dialogue"], Literal["sfx"]] = ("dialogue", "sfx")
            bars = (bytearray(), bytearray())
            with ExitStack() as stack:
                outputs = [
                    stack.enter_context(wave.open(str(directory / f"{kind}.wav"), "wb"))
                    for kind in stems
                ]
                for audio in outputs:
                    audio.setparams((2, 2, _RATE, 0, "NONE", "not compressed"))
                while (
                    chunk := np.fromfile(raw, dtype="<f4", count=2 * rate * channels)
                ).size:
                    samples = chunk.reshape(-1, channels)
                    voice = samples[:, 2:]
                    for output, peaks, stem in zip(
                        outputs, bars, (voice, samples[:, :2] - voice), strict=True
                    ):
                        peaks.extend(_peaks(stem, rate))
                        _write_wave(output, stem)
            for kind, peaks in zip(stems, bars, strict=True):
                if encoded := _encode_peaks(peaks):
                    data["stems"].append({"kind": kind, "peaks": encoded})
                else:
                    (
                        directory / f"{kind}.wav"
                    ).unlink()  # Staged silent derivative, not a user file.
        else:
            peaks = bytearray()
            while (
                chunk := np.fromfile(raw, dtype="<f4", count=2 * rate * channels)
            ).size:
                peaks.extend(_peaks(chunk.reshape(-1, channels), rate))
            data["peaks"] = _encode_peaks(peaks)
        (directory / metadata.name).write_text(json.dumps(data), encoding="utf-8")
        try:
            directory.replace(target)
        except OSError:
            if not metadata.is_file():
                raise
            return json.loads(metadata.read_bytes())
    return data


async def timeline_audio(source: Path, cache: Path, split: bool) -> AudioAnalysis:
    info = await asyncio.to_thread(source.stat)
    if not stat.S_ISREG(info.st_mode):
        raise FileNotFoundError(source)
    key = hashlib.sha256(
        f"rnnoise-v1:{source}:{info.st_mtime_ns}:{info.st_size}:{split}".encode()
    ).hexdigest()
    target = cache / key
    metadata = target / "peaks.json"

    def read_cached() -> AudioAnalysis | None:
        try:
            return json.loads(metadata.read_bytes())
        except FileNotFoundError:
            return None

    if (cached := await asyncio.to_thread(read_cached)) is not None:
        return cached
    if target not in _JOBS:

        async def run() -> AudioAnalysis:
            async with _LIMIT:
                return await asyncio.to_thread(_analyse, source, target, split, info)

        task = _JOBS[target] = asyncio.create_task(run())

        def finished(job: asyncio.Task[AudioAnalysis]) -> None:
            _JOBS.pop(target, None)
            if not job.cancelled():
                job.exception()

        task.add_done_callback(finished)
    return await asyncio.shield(_JOBS[target])


async def timeline_stem_paths(source: Path, cache: Path) -> dict[StemKind, Path]:
    try:
        analysis = await timeline_audio(source, cache, True)
    except (OSError, ValueError, subprocess.SubprocessError, FfmpegUnavailableError) as exc:
        raise ValueError("Audio separation failed") from exc
    return {stem["kind"]: cache / analysis["key"] / f"{stem['kind']}.wav" for stem in analysis["stems"]}
