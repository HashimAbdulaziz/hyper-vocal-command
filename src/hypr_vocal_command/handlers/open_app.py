"""OPEN_APP: launches an installed application by its spoken name.

The spoken name is resolved through the config alias map (never exec'd directly) into
either a flatpak app-id or a native binary resolved on PATH.
"""

import shlex
import shutil
import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class OpenAppArgs(BaseModel):
    app_name: str


@intent_handler(
    "OPEN_APP",
    OpenAppArgs,
    description=(
        "Launch a named installed application OR run a named utility script/shortcut "
        "bound to one spoken name, e.g. 'open obsidian', 'task list', 'start task', "
        "'toggle timer', 'lock screen' -- anything that is one specific pre-registered launchable "
        "command, other than a terminal or file manager (their own dedicated intents)."
    ),
)
def open_app(args: OpenAppArgs, config: Config) -> ExecutionResult:
    alias = config.resolve_app(args.app_name)
    if alias is None:
        return ExecutionResult(ok=False, message=f"Unknown app: {args.app_name!r}")

    if alias.manager == "flatpak":
        cmd = ["flatpak", "run", alias.identifier]
    else:
        # identifier may be more than one token (e.g. an `env VAR=value real_command`
        # wrapper discovered by scan-apps) — only argv[0] is resolved against PATH.
        argv = shlex.split(alias.identifier)
        binary = shutil.which(argv[0]) if argv else None
        if binary is None:
            return ExecutionResult(ok=False, message=f"Binary not found on PATH: {alias.identifier}")
        cmd = [binary, *argv[1:]]

    subprocess.Popen(
        cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return ExecutionResult(ok=True, message=f"Opened {args.app_name} ({' '.join(cmd)}).")
