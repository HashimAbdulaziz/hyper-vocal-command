"""CLOSE_APP: closes a named application's window wherever it is -- even on a
different workspace or unfocused -- distinct from HYPRLAND_ACTION's close_window
action, which only ever closes whichever window currently has focus.

Dispatches `hyprctl dispatch closewindow class:^(...)$` directly, the same IPC
mechanism used elsewhere in this project -- no keypress simulation, no find-then-kill
two-step. Confirmed live against a real window: `hyprctl dispatch closewindow` always
exits 0 regardless of whether anything matched, so success/failure is read from stdout
text ("ok" vs "closeWindow: no window found"), not the exit code.
"""

import re
import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class CloseAppArgs(BaseModel):
    app_name: str


@intent_handler(
    "CLOSE_APP",
    CloseAppArgs,
    description=(
        "Close/kill a named application's window, wherever it is -- even on a "
        "different workspace or not currently focused. `app_name` must be a real, "
        "specific application name (e.g. 'spotify', 'vscode', 'chrome'). NOT for "
        "'close this window'/'close this tile'/'close it'/'kill this' -- generic words "
        "or pronouns with no real app named (use HYPRLAND_ACTION for those instead -- "
        "they mean whichever window is CURRENTLY FOCUSED, a different thing entirely)."
    ),
)
def close_app(args: CloseAppArgs, config: Config) -> ExecutionResult:
    window_class = config.resolve_app_window_class(args.app_name)
    if window_class is None:
        return ExecutionResult(ok=False, message=f"Unknown app: {args.app_name!r}")

    pattern = f"class:^({re.escape(window_class)})$"
    result = subprocess.run(
        ["hyprctl", "dispatch", "closewindow", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"Failed to close {args.app_name!r}: {result.stderr.strip()[:200]}"
        )
    if "no window found" in result.stdout.lower():
        return ExecutionResult(ok=False, message=f"{args.app_name} isn't currently open.")
    return ExecutionResult(ok=True, message=f"Closed {args.app_name}.")
