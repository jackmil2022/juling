"""Run the desktop window's private ASGI server until its stdin pipe closes."""

import os
import socket
import sys
from threading import Thread
from time import sleep

import uvicorn


def _wait_for_stdin_close() -> None:
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        # A pending ReadFile on stdin blocks native libraries that inspect the pipe handle.
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(sys.stdin.fileno()))
        peek = ctypes.WinDLL("kernel32").PeekNamedPipe
        while peek(handle, None, 0, None, None, None):
            sleep(0.1)
    else:
        while os.read(sys.stdin.fileno(), 4096):
            pass


class DesktopServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started and sockets:
            port = sockets[0].getsockname()[1]
            print(f"JULING_DESKTOP_READY http://127.0.0.1:{port}", flush=True)


def main():
    with socket.socket() as listener:
        if sys.platform == "win32":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        os.environ["AUTH_ENABLED"] = "false"
        server = DesktopServer(uvicorn.Config("server.app:app", timeout_graceful_shutdown=5))

        def stop_on_close():
            try:
                _wait_for_stdin_close()
            finally:
                server.should_exit = True

        Thread(target=stop_on_close, daemon=True).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
