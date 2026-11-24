"""Replace older Windows processes that belong to this 剧灵 checkout."""

import ctypes as c
import os
import sys
from contextlib import ExitStack
from ctypes import wintypes as w
from pathlib import Path
from time import monotonic


class ProcessEntry(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD), ("heap", c.c_size_t),
        ("module", w.DWORD), ("threads", w.DWORD), ("parent", w.DWORD), ("priority", w.LONG),
        ("flags", w.DWORD), ("name", w.WCHAR * 260),
    ]


class UnicodeString(c.Structure):
    _fields_ = [("length", w.USHORT), ("capacity", w.USHORT), ("buffer", c.c_void_p)]


def api(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


kernel = c.WinDLL("kernel32", use_last_error=True)
snapshot_processes = api(kernel, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
first_process = api(kernel, "Process32FirstW", w.BOOL, w.HANDLE, c.POINTER(ProcessEntry))
next_process = api(kernel, "Process32NextW", w.BOOL, w.HANDLE, c.POINTER(ProcessEntry))
open_process = api(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
close_handle = api(kernel, "CloseHandle", w.BOOL, w.HANDLE)
process_times = api(kernel, "GetProcessTimes", w.BOOL, w.HANDLE, *([c.POINTER(c.c_uint64)] * 4))
process_image = api(kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
terminate_process = api(kernel, "TerminateProcess", w.BOOL, w.HANDLE, w.UINT)
wait_for_exit = api(kernel, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
query_process = api(c.WinDLL("ntdll"), "NtQueryInformationProcess", w.LONG, w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p)
command_to_argv = api(c.WinDLL("shell32"), "CommandLineToArgvW", c.POINTER(w.LPWSTR), w.LPCWSTR, c.POINTER(c.c_int))
local_free = api(kernel, "LocalFree", c.c_void_p, c.c_void_p)


def process_snapshot():
    snapshot = snapshot_processes(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        entry = ProcessEntry(size=c.sizeof(ProcessEntry))
        if not first_process(snapshot, c.byref(entry)):
            raise c.WinError(c.get_last_error())
        processes = {}
        while True:
            processes[entry.pid] = (entry.parent, entry.name.lower())
            if not next_process(snapshot, c.byref(entry)):
                return processes
    finally:
        close_handle(snapshot)


def created_at(handle):
    times = [c.c_uint64() for _ in range(4)]
    return times[0].value if process_times(handle, *times) else None


def process_command(handle):
    image = c.create_unicode_buffer(32768)
    length = w.DWORD(len(image))
    if not process_image(handle, 0, image, c.byref(length)):
        return "", []
    buffer = c.create_string_buffer(65536 + c.sizeof(UnicodeString))
    # ProcessCommandLineInformation (60) returns a counted Unicode string in this buffer.
    if query_process(handle, 60, buffer, len(buffer), None) < 0:
        return "", []
    command = UnicodeString.from_buffer(buffer)
    if not command.length:
        return "", []
    argc = c.c_int()
    argv = command_to_argv(c.wstring_at(command.buffer, command.length // 2), c.byref(argc))
    if not argv:
        return "", []
    try:
        return os.path.normcase(image.value), argv[1:argc.value]
    finally:
        local_free(argv)


_ROOT_MARKERS = ("juling_root=", bytes.fromhex("6172637265656c5f726f6f743d").decode("ascii"))


def belongs_to_project(image, args, root):
    if not args:
        return False
    first = os.path.normcase(os.path.normpath(args[0]))
    executable = os.path.basename(image)
    if executable in {"electron.exe", "node.exe"}:
        if first in (root + r"\desktop\main.cjs", root + r"\frontend\node_modules\vite\bin\vite.js"):
            return True
    if image.startswith(root + "\\frontend\\node_modules\\") and image.endswith(r"\electron\dist\electron.exe"):
        if first in (r"..\desktop\main.cjs", r"desktop\main.cjs"):
            return True
    if image == root + r"\.venv\scripts\uvicorn.exe":
        return "server.app:app" in args
    if executable not in {"python.exe", "pythonw.exe"} or "-m" not in args:
        return False
    index = args.index("-m")
    if any(not flag.startswith("-") and not flag.startswith(_ROOT_MARKERS) for flag in args[:index]):
        return False
    if any(flag in args[:index] for flag in ("-c", "--")):
        return False
    entry = args[index + 1 :]
    if entry[:1] == ["server.desktop"]:
        for flag, marker in zip(args[:index], args[1:index]):
            if flag == "-X" and marker.startswith(_ROOT_MARKERS):
                return os.path.normcase(marker.split("=", 1)[1]) == root
    if image != root + r"\.venv\scripts\python.exe":
        return False
    return entry[:1] == ["server.desktop"] or (entry[:1] == ["uvicorn"] and "server.app:app" in entry[1:])


def replace_older_instances(current_pid, deadline):
    root = os.path.normcase(str(Path(__file__).resolve().parents[1]))
    processes = process_snapshot()
    with ExitStack() as handles:
        def open_for_check(pid, terminate=False):
            access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
            if terminate:
                access |= 0x100001  # SYNCHRONIZE | PROCESS_TERMINATE
            handle = open_process(access, False, pid)
            if handle:
                handles.callback(close_handle, handle)
            return handle

        current = open_for_check(current_pid)
        current_start = created_at(current) if current else None
        if current_start is None:
            raise RuntimeError("无法识别当前 剧灵 进程。")

        targets = {}
        for pid, (_, name) in processes.items():
            if name not in {"electron.exe", "node.exe", "python.exe", "pythonw.exe", "uvicorn.exe"}:
                continue
            handle = open_for_check(pid, terminate=True)
            start = created_at(handle) if handle else None
            if start is not None and start < current_start and belongs_to_project(*process_command(handle), root):
                targets[pid] = (handle, start)

        children = {}
        for pid, (parent, _) in processes.items():
            children.setdefault(parent, []).append(pid)
        pending = list(targets)
        for parent in pending:
            for pid in children.get(parent, ()):
                if pid in targets or pid == current_pid:
                    continue
                handle = open_for_check(pid, terminate=True)
                start = created_at(handle) if handle else None
                if start is not None and targets[parent][1] <= start:
                    targets[pid] = (handle, start)
                    pending.append(pid)

        # Retain verified handles through termination so a reused PID cannot become a target.
        for handle, _ in targets.values():
            if monotonic() >= deadline:
                raise RuntimeError("启动自检超时。")
            if not terminate_process(handle, 1) and wait_for_exit(handle, 0) != 0:
                raise c.WinError(c.get_last_error())
        for handle, _ in targets.values():
            remaining = max(0, int((deadline - monotonic()) * 1000))
            if wait_for_exit(handle, remaining) != 0:
                raise RuntimeError("旧 剧灵 进程未在启动时限内退出。")
    return len(targets)


if __name__ == "__main__":
    started = monotonic()
    count = replace_older_instances(int(sys.argv[1]), started + 0.75)
    print(f"stopped={count} elapsed_ms={round((monotonic() - started) * 1000)}")
