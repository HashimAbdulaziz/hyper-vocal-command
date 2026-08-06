"""MOVE_TO_WORKSPACE: sends the focused window to another workspace.

Mirrors this machine's `SUPER+SHIFT+1..5` binds (`movetoworkspace N`). Deliberately a
separate intent from WORKSPACE_SWITCH rather than a flag on it: "go to workspace 2" and
"send this window to workspace 2" leave you in completely different places, and a
misread flag would silently relocate a window instead of just navigating. Two intents
make the confusion a wrong-intent error the confidence gate can catch, rather than a
one-boolean slip.

Only absolute workspace numbers are accepted -- there is no "move it to the next
workspace" phrasing in this user's own keybinds, and inventing relative movement here
would mean guessing at a destination the user never named.
"""

import subprocess
from typing import Annotated

from pydantic import BaseModel, Field

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class MoveToWorkspaceArgs(BaseModel):
    workspace: Annotated[int, Field(ge=1, le=99)]


@intent_handler(
    "MOVE_TO_WORKSPACE",
    MoveToWorkspaceArgs,
    description=(
        "Move/send the CURRENT window to a numbered workspace, e.g. 'move this window "
        "to workspace 2', 'send this to workspace 3'. The user stays put is NOT implied "
        "-- Hyprland follows the window. Use WORKSPACE_SWITCH instead when the user "
        "only wants to GO to another workspace without taking the window with them; the "
        "giveaway is a verb like move/send/put/take plus a reference to this window."
    ),
)
def move_to_workspace(args: MoveToWorkspaceArgs, config: Config) -> ExecutionResult:
    result = subprocess.run(
        ["hyprctl", "dispatch", "movetoworkspace", str(args.workspace)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"Failed to move window: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message=f"Moved window to workspace {args.workspace}.")
