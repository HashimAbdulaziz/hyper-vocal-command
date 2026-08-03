"""UPDATE_PACKAGE: updates a package via its scoped, allow-listed dnf/flatpak command.

requires_confirmation=True — the executor blocks this intent unconditionally until
Phase 10 builds a real confirmation flow, so this handler is currently unreachable in
practice. It's still implemented now so the mechanism (alias resolution, argv
construction, the narrow sudoers rule) can be exercised directly once Phase 10 lands.
"""

import subprocess

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class UpdatePackageArgs(BaseModel):
    package_name: str


@intent_handler(
    "UPDATE_PACKAGE",
    UpdatePackageArgs,
    requires_confirmation=True,
    description=(
        "Update ONE named installed package/application, e.g. 'update vscode'. Use "
        "UPDATE_SYSTEM instead when the user wants to update everything of a kind "
        "(e.g. 'update dnf', 'update all flatpak packages') rather than a specific app."
    ),
)
def update_package(args: UpdatePackageArgs, config: Config) -> ExecutionResult:
    alias = config.resolve_package(args.package_name)
    if alias is None:
        return ExecutionResult(ok=False, message=f"Unknown package: {args.package_name!r}")

    if alias.manager == "flatpak":
        cmd = ["flatpak", "update", "-y", alias.identifier]
    else:
        cmd = ["sudo", "-n", "/usr/bin/dnf", "update", "-y", alias.identifier]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ExecutionResult(
            ok=False,
            message=f"Update failed for {args.package_name!r}: {result.stderr.strip()[:200]}",
        )
    return ExecutionResult(ok=True, message=f"Updated {args.package_name}.")
