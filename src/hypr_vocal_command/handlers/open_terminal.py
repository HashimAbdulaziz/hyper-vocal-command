"""OPEN_TERMINAL: launches the configured terminal emulator."""

import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class OpenTerminalArgs(BaseModel):
    pass


@intent_handler(
    "OPEN_TERMINAL",
    OpenTerminalArgs,
    description=(
        "Open a new terminal window. Use this for any request to open a terminal, "
        "console, or shell -- never OPEN_APP for this."
    ),
)
def open_terminal(args: OpenTerminalArgs, config: Config) -> ExecutionResult:
    cmd = config.terminal_cmd
    subprocess.Popen(
        cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return ExecutionResult(ok=True, message=f"Opened terminal ({cmd[0]}).")
