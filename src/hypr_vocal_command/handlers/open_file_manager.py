"""OPEN_FILE_MANAGER: launches the configured file manager."""

import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class OpenFileManagerArgs(BaseModel):
    pass


@intent_handler(
    "OPEN_FILE_MANAGER", OpenFileManagerArgs, description="Open the file manager / file browser."
)
def open_file_manager(args: OpenFileManagerArgs, config: Config) -> ExecutionResult:
    cmd = config.file_manager_cmd
    subprocess.Popen(
        cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return ExecutionResult(ok=True, message=f"Opened file manager ({cmd[0]}).")
