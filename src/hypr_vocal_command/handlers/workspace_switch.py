"""WORKSPACE_SWITCH: jumps to a Hyprland workspace via `hyprctl dispatch workspace` -- the
same IPC mechanism Hyprland's own `bind = SUPER, N, workspace, N` keybinds use.

Supports both an absolute workspace number and relative "next"/"previous" navigation,
matching what Hyprland's `workspace` dispatcher natively accepts (`+1` / `previous` --
the same `previous` keyword this user's own `SUPER+TAB` bind already uses).
"""

import subprocess
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..config import Config
from ..registry import ExecutionResult, intent_handler

_RELATIVE_DISPATCH_ARGS = {"next": "+1", "previous": "previous"}


class WorkspaceSwitchArgs(BaseModel):
    workspace: Annotated[int, Field(ge=1, le=99)] | Literal["next", "previous"]


@intent_handler(
    "WORKSPACE_SWITCH",
    WorkspaceSwitchArgs,
    description=(
        "Switch to a workspace/screen -- the user may say 'workspace' or 'screen'. "
        "`workspace` is either a number (e.g. 'go to workspace 2' -> 2) or, for relative "
        "requests with no number (e.g. 'go to the next workspace', 'go back a workspace'), "
        "the literal string 'next' or 'previous' -- never guess a number for these."
    ),
)
def workspace_switch(args: WorkspaceSwitchArgs, config: Config) -> ExecutionResult:
    dispatch_arg = (
        _RELATIVE_DISPATCH_ARGS[args.workspace]
        if isinstance(args.workspace, str)
        else args.workspace
    )

    result = subprocess.run(
        ["hyprctl", "dispatch", "workspace", str(dispatch_arg)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"Failed to switch workspace: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message=f"Switched to workspace {args.workspace}.")
