"""Scans installed .desktop files and generates OPEN_APP/UPDATE_PACKAGE alias entries.

This is what broadens the alias map beyond Phase 1's hand-seeded examples to whatever is
actually installed on the machine, without ever hand-typing more entries. Output is written
to apps.generated.toml, a separate file from config.toml so re-running the scan never
clobbers hand-made corrections (see config.load_config's merge order).
"""

import re
import shlex
import shutil
import subprocess
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import AppAlias, PackageAlias, normalize_text

FIELD_CODES = {"%f", "%F", "%u", "%U", "%i", "%c", "%k", "%v", "%m"}

DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path.home() / ".local/share/applications",
]

_BARE_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class AppEntry:
    key: str
    name: str
    surface_forms: tuple[str, ...]
    manager: Literal["native", "flatpak"]
    identifier: str
    package_name: str | None


def _strip_field_codes(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in FIELD_CODES]


def _parse_exec(exec_line: str) -> list[str] | None:
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        return None
    tokens = _strip_field_codes(tokens)
    return tokens or None


def _skip_env_wrapper(tokens: list[str]) -> list[str]:
    """Skip a leading `env [VAR=value ...] real_command ...` wrapper, if present.

    Common for apps that need environment variables set before exec (e.g. vocalinux's own
    `Exec=env GI_TYPELIB_PATH= .../vocalinux-gui`) — without this, the "app" would be
    misidentified as plain `env` for both package-name attribution and surface forms.
    """
    if not tokens or Path(tokens[0]).name != "env":
        return tokens
    idx = 1
    while idx < len(tokens) and not tokens[idx].startswith("-") and "=" in tokens[idx]:
        idx += 1
    return tokens[idx:] if idx < len(tokens) else tokens


def _flatpak_app_id(tokens: list[str]) -> str | None:
    if len(tokens) < 2 or Path(tokens[0]).name != "flatpak" or tokens[1] != "run":
        return None
    for token in tokens[2:]:
        if not token.startswith("-"):
            return token
    return None


def _reverse_rpm_lookup(binary_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["rpm", "-qf", "--queryformat", "%{NAME}", binary_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_desktop_file(path: Path) -> AppEntry | None:
    parser = ConfigParser(interpolation=None, strict=False)
    try:
        with path.open(encoding="utf-8") as f:
            parser.read_file(f)
    except (OSError, UnicodeDecodeError, ConfigParserError):
        # .desktop files are arbitrary system content; skip anything malformed rather
        # than aborting the whole scan.
        return None

    if not parser.has_section("Desktop Entry"):
        return None
    entry = parser["Desktop Entry"]

    if entry.get("Type", "Application") != "Application":
        return None
    if entry.getboolean("NoDisplay", fallback=False):
        return None
    if entry.getboolean("Hidden", fallback=False):
        return None

    name = entry.get("Name")
    exec_line = entry.get("Exec")
    if not name or not exec_line:
        return None

    tokens = _parse_exec(exec_line)
    if not tokens:
        return None

    flatpak_id = _flatpak_app_id(tokens)
    manager: Literal["native", "flatpak"]
    if flatpak_id is not None:
        manager = "flatpak"
        identifier = flatpak_id
        package_name = None
        surface_forms = {normalize_text(name)}
    else:
        resolved = shutil.which(tokens[0])
        if resolved is None:
            return None
        effective_tokens = _skip_env_wrapper(tokens)
        primary = effective_tokens[0] if effective_tokens else tokens[0]
        primary_resolved = shutil.which(primary) or resolved
        manager = "native"
        # The full token list (not just the binary) is kept so wrapper commands like the
        # `env` case above still execute correctly — see handlers/open_app.py.
        identifier = shlex.join(tokens)
        package_name = _reverse_rpm_lookup(primary_resolved)
        surface_forms = {normalize_text(name), normalize_text(Path(primary).name)}

    return AppEntry(
        key=path.stem,
        name=name,
        surface_forms=tuple(sorted(surface_forms)),
        manager=manager,
        identifier=identifier,
        package_name=package_name,
    )


def discover_apps(desktop_dirs: list[Path] | None = None) -> list[AppEntry]:
    dirs = desktop_dirs if desktop_dirs is not None else DESKTOP_DIRS
    entries: dict[str, AppEntry] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for desktop_file in sorted(directory.glob("*.desktop")):
            entry = _parse_desktop_file(desktop_file)
            if entry is not None:
                entries[entry.key] = entry
    return sorted(entries.values(), key=lambda e: e.key)


def to_app_alias(entry: AppEntry) -> AppAlias:
    return AppAlias(
        surface_forms=list(entry.surface_forms),
        manager=entry.manager,
        identifier=entry.identifier,
    )


def to_package_alias(entry: AppEntry) -> PackageAlias | None:
    if entry.manager == "flatpak":
        return PackageAlias(
            surface_forms=list(entry.surface_forms),
            manager="flatpak",
            identifier=entry.identifier,
        )
    if entry.package_name:
        return PackageAlias(
            surface_forms=list(entry.surface_forms),
            manager="dnf",
            identifier=entry.package_name,
        )
    return None


def build_generated_aliases(
    entries: list[AppEntry],
) -> tuple[dict[str, AppAlias], dict[str, PackageAlias]]:
    apps = {entry.key: to_app_alias(entry) for entry in entries}
    packages: dict[str, PackageAlias] = {}
    for entry in entries:
        package_alias = to_package_alias(entry)
        if package_alias is not None:
            packages[entry.key] = package_alias
    return apps, packages


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_string_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def _toml_key(key: str) -> str:
    return key if _BARE_TOML_KEY_RE.match(key) else _toml_string(key)


def render_generated_toml(
    app_aliases: dict[str, AppAlias], package_aliases: dict[str, PackageAlias]
) -> str:
    lines = [
        "# Auto-generated by `hypr-vocal-command scan-apps --write`.",
        "# Do not hand-edit -- reruns of scan-apps overwrite this file.",
        "# To override a specific entry, add it to config.toml instead.",
        "",
    ]
    for key, alias in sorted(app_aliases.items()):
        lines.append(f"[apps.{_toml_key(key)}]")
        lines.append(f"surface_forms = {_toml_string_array(alias.surface_forms)}")
        lines.append(f"manager = {_toml_string(alias.manager)}")
        lines.append(f"identifier = {_toml_string(alias.identifier)}")
        lines.append("")
    for key, pkg_alias in sorted(package_aliases.items()):
        lines.append(f"[packages.{_toml_key(key)}]")
        lines.append(f"surface_forms = {_toml_string_array(pkg_alias.surface_forms)}")
        lines.append(f"manager = {_toml_string(pkg_alias.manager)}")
        lines.append(f"identifier = {_toml_string(pkg_alias.identifier)}")
        lines.append("")
    return "\n".join(lines)


def write_generated_apps(entries: list[AppEntry], path: Path) -> None:
    apps, packages = build_generated_aliases(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_generated_toml(apps, packages))
