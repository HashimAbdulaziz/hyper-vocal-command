"""HYPRLAND_ACTION: invokes a named Hyprland compositor action (close window, toggle
floating, etc.) directly via `hyprctl dispatch` -- the same IPC mechanism Hyprland's own
keybinds use internally. No keypress simulation involved.

Most actions implicitly act on the focused window, so they need no targeting. Actions
whose alias sets `target_active_class` are the exception: they resolve the focused
window's address at runtime and refuse if the wrong kind of window is focused, rather
than acting on an arbitrary window that merely matches the class.
"""

import json
import subprocess

from pydantic import BaseModel

from ..config import Config, HyprlandActionAlias
from ..registry import ExecutionResult, intent_handler


def _active_window() -> dict:
    """The focused window as Hyprland reports it, or {} when nothing is focused."""
    result = subprocess.run(
        ["hyprctl", "activewindow", "-j"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _resolve_active_target(alias: HyprlandActionAlias) -> tuple[str | None, str | None]:
    """(args_with_address, error). Refuses unless the focused window is the expected app
    -- acting on a different window of the same class would hit something the user isn't
    looking at, and for a tab-close that silently destroys the wrong page."""
    window = _active_window()
    if window.get("class") != alias.target_active_class:
        focused = window.get("class") or "nothing"
        return None, (
            f"That only works on the focused {alias.target_active_class} window "
            f"(currently focused: {focused})."
        )
    address = window.get("address")
    if not address:
        return None, "Could not determine the focused window's address."
    return f"{alias.args},address:{address}", None


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

    dispatch_args = alias.args
    if alias.target_active_class is not None:
        targeted, error = _resolve_active_target(alias)
        if targeted is None:
            return ExecutionResult(ok=False, message=error or "No focused window to target.")
        dispatch_args = targeted

    cmd = ["hyprctl", "dispatch", alias.dispatcher]
    if dispatch_args:
        cmd.append(dispatch_args)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"hyprctl dispatch failed: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message=f"Ran {alias.dispatcher} {alias.args}".strip())
