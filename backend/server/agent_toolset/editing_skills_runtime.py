"""Fixed entry points for the pinned third-party editing tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from functools import partial
from pathlib import Path

from lib.infra.ffmpeg import ffmpeg_executable, local_file_input
from lib.infra.subprocess_deadline import SubprocessDeadlineExceeded, run_with_deadline

ROOT = Path(__file__).resolve().parents[3] / "third_party" / "editing"


class EditingSkillError(RuntimeError):
    pass


async def run_skill(checkout: str, args: list[str], workspace: Path, *, python_root: Path | None = None):
    if not (ROOT / "installed" / checkout).is_file() or not (ROOT / checkout).is_dir():
        raise EditingSkillError(f"{checkout} 尚未安装，请运行 desktop/build.ps1。")
    runtime = ROOT / "runtime"
    if not all((runtime / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")):
        raise EditingSkillError("剪辑 Skill 的 FFmpeg 工具未安装，请运行 desktop/build.ps1。")
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    env.update(PATH=str(runtime), TMP=str(workspace), TEMP=str(workspace),
               PYTHONUTF8="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", FFMPEG_SKILL_TIMEOUT="60")
    if python_root is not None:
        env["PYTHONPATH"] = str(python_root)
    try:
        result = await run_with_deadline(
            [sys.executable, "-P", *args], deadline_seconds=90, capture_stdout=True, capture_stderr=True,
            cwd=workspace, spawn=partial(asyncio.create_subprocess_exec, env=env),
        )
    except (OSError, SubprocessDeadlineExceeded) as exc:
        raise EditingSkillError(f"{checkout} 无法运行：{exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-700:]
        raise EditingSkillError(f"{checkout} 运行失败（{result.returncode}）：{detail}")
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, ValueError) as exc:
        raise EditingSkillError(f"{checkout} 返回的结果不是 JSON。") from exc


async def stage_window(source: Path, output: Path, start: float, end: float, *, filters: list[str] | None = None):
    """Pass only a re-encoded local window to tools that accept arbitrary media containers."""
    if end <= start:
        raise EditingSkillError("没有可分析的素材区间。")
    args = [ffmpeg_executable(), "-nostdin", "-v", "error", "-ss", f"{start:.6f}", *local_file_input(source),
            "-t", f"{end-start:.6f}", "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
            "-map_chapters", "-1", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-c:a", "aac"]
    if filters:
        args += ["-af", ",".join(filters)]
    try:
        result = await run_with_deadline([*args, str(output)], deadline_seconds=120, capture_stderr=True)
    except (OSError, SubprocessDeadlineExceeded) as exc:
        raise EditingSkillError(f"无法准备分析片段：{exc}") from exc
    if result.returncode:
        raise EditingSkillError(result.stderr.decode(errors="replace").strip()[-700:])
