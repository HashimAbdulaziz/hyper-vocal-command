"""HYPRLAND_ACTION: invokes a named Hyprland compositor action (close window, toggle
floating, etc.) directly via `hyprctl dispatch` -- the same IPC mechanism Hyprland's own
keybinds use internally. No keypress simulation involved.
"""

import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class HyprlandActionArgs(BaseModel):
    action: str


@intent_handler(
    "HYPRLAND_ACTION",
    HyprlandActionArgs,
    description=(
        "Trigger a named window-manager action on the CURRENTLY FOCUSED window only, "
        "e.g. 'close this window', 'toggle floating', 'fullscreen this' (true "
        "fullscreen, hides the bar), 'maximize this window' (keeps the bar, a distinct "
        "action from fullscreen), 'toggle split', or 'show/hide/toggle scratchpad' (a "
        "special always-available floating workspace -- not a new terminal or app). "
        "If a specific app is named instead (e.g. 'close spotify', 'kill spotify'), use "
        "CLOSE_APP instead -- that targets the named app wherever it is, not just "
        "whatever's focused right now. "
        "Not for opening applications (use OPEN_APP / OPEN_TERMINAL / OPEN_FILE_MANAGER "
        "instead) and not for switching workspaces (use WORKSPACE_SWITCH instead)."
    ),
)
def hyprland_action(args: HyprlandActionArgs, config: Config) -> ExecutionResult:
    alias = config.resolve_hyprland_action(args.action)
    if alias is None:
        return ExecutionResult(ok=False, message=f"Unknown window action: {args.action!r}")

    cmd = ["hyprctl", "dispatch", alias.dispatcher]
    if alias.args:
        cmd.append(alias.args)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"hyprctl dispatch failed: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message=f"Ran {alias.dispatcher} {alias.args}".strip())
