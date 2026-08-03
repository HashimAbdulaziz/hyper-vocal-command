"""Production hotkey trigger -- stdlib-only, deliberately a different weight class from
`cli.py`. Importing pydantic/httpx/pywhispercpp here (even transitively, via the rest of
the package) would defeat the entire point of the warm-daemon architecture: this is the
thing a Hyprland keybind execs on every single hotkey press, so its own startup cost is
pure overhead added to every voice command, on top of whatever the warm daemon needs.

Fire-and-forget by design: sends one request and exits immediately, without waiting for
the multi-second pipeline result -- all user-facing feedback (both "heard X -> intent"
and the execution result) already comes from the daemon's own desktop notifications, not
from this script's output. `time`-ing an invocation of this should show a number close
to the bare Python-interpreter startup floor, not the pipeline's own latency.
"""

import argparse
import json
import os
import socket
import subprocess
import sys


def _notify(title: str, body: str) -> None:
    try:
        subprocess.run(["notify-send", "--app-name=hypr-vocal-command", title, body], check=False)
    except OSError:
        pass


def _socket_path() -> str:
    xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not xdg_runtime_dir:
        raise RuntimeError("XDG_RUNTIME_DIR is not set")
    return os.path.join(xdg_runtime_dir, "hypr-vocal-command.sock")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en", choices=["en", "ar"])
    args = parser.parse_args()

    try:
        path = _socket_path()
    except RuntimeError as exc:
        _notify("hypr-vocal-command", str(exc))
        return 1

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        sock.sendall((json.dumps({"language": args.lang}) + "\n").encode())
    except OSError as exc:
        _notify("hypr-vocal-command", f"Daemon not reachable: {exc}")
        return 1
    finally:
        sock.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
