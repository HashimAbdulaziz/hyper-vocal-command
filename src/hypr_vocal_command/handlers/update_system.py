"""UPDATE_SYSTEM: bulk-updates ALL packages of a given kind (dnf, flatpak, or both) --
distinct from UPDATE_PACKAGE, which targets one specific named app/package.

requires_confirmation=True -- inert until Phase 10, same as UPDATE_PACKAGE. This handler
must NEVER be given a password to type or speak (see the project's Cross-Cutting Decision
5): the dnf path only ever works through a pre-installed, scoped sudoers NOPASSWD rule and
fails fast (`sudo -n`) if that rule is missing, rather than hanging on or requesting a
password. The flatpak path may pop its own polkit graphical prompt, handled entirely by the
OS outside this pipeline.
"""

import subprocess
from typing import Literal

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class UpdateSystemArgs(BaseModel):
    scope: Literal["dnf", "flatpak", "all"]


def _update_dnf() -> tuple[bool, str]:
    result = subprocess.run(
        ["sudo", "-n", "/usr/bin/dnf", "update", "-y"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return False, f"dnf update failed: {result.stderr.strip()[:200]}"
    return True, "dnf packages updated."


def _update_flatpak() -> tuple[bool, str]:
    result = subprocess.run(
        ["flatpak", "update", "-y"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return False, f"flatpak update failed: {result.stderr.strip()[:200]}"
    return True, "flatpak packages updated."


@intent_handler(
    "UPDATE_SYSTEM",
    UpdateSystemArgs,
    requires_confirmation=True,
    description=(
        "Update ALL packages of a given kind, not one named app -- e.g. 'update dnf', "
        "'update all flatpak packages', 'update my system'. args.scope is 'dnf', "
        "'flatpak', or 'all'. Use UPDATE_PACKAGE instead whenever the user names one "
        "specific app or package."
    ),
)
def update_system(args: UpdateSystemArgs, config: Config) -> ExecutionResult:
    messages = []
    ok = True

    if args.scope in ("dnf", "all"):
        success, message = _update_dnf()
        ok = ok and success
        messages.append(message)

    if args.scope in ("flatpak", "all"):
        success, message = _update_flatpak()
        ok = ok and success
        messages.append(message)

    return ExecutionResult(ok=ok, message=" ".join(messages))
