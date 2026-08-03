"""Loads and validates hypr-vocal-command configuration."""

import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class AppAlias(BaseModel):
    surface_forms: list[str]
    manager: Literal["native", "flatpak"]
    identifier: str
    # Hyprland's actual window `class` for this app, used by CLOSE_APP to target the
    # right window regardless of focus/workspace. Often NOT the same as `identifier`
    # (e.g. vscode's identifier is "code" for launching, which happens to also be its
    # class -- but flatpak identifiers like "com.spotify.Client" never match the real
    # class at all, which is just "spotify"). Defaults to None; CLOSE_APP falls back to
    # guessing the alias's own registry key, which happens to be correct for many simple
    # apps (confirmed for spotify) but not all -- set this explicitly when the guess is
    # wrong for a given app, the same "hand-curate as gaps are found" pattern used
    # everywhere else in this file.
    window_class: str | None = None


class PackageAlias(BaseModel):
    surface_forms: list[str]
    manager: Literal["dnf", "flatpak"]
    identifier: str


class HyprlandActionAlias(BaseModel):
    surface_forms: list[str]
    dispatcher: str
    args: str = ""


DEFAULT_APPS: dict[str, AppAlias] = {
    "obsidian": AppAlias(
        surface_forms=["obsidian"],
        manager="flatpak",
        identifier="md.obsidian.Obsidian",
        # Real Hyprland window class is "md.Obsidian" (mixed case!), not the registry
        # key "obsidian" -- confirmed by launching a real instance and checking
        # `hyprctl clients -j`. Same class of mismatch as vscode's override below.
        window_class="md.Obsidian",
    ),
    "spotify": AppAlias(
        # "play music"/"run music"/etc. deliberately NOT registered here -- those are
        # ambiguous between "launch the app" and "resume paused playback", which only
        # MEDIA_CONTROL's handler can disambiguate at runtime (by checking whether
        # Spotify is already running). This alias stays for direct, explicit launches.
        surface_forms=[
            "spotify",
            # Known whisper mis-hearings of "spotify" -- vocabulary priming helps but
            # doesn't guarantee correct transcription; these are a deterministic backstop
            # so alias resolution still succeeds if the LLM passes the garbled text
            # through verbatim as app_name.
            "putify",
            "this putify",
        ],
        manager="flatpak",
        identifier="com.spotify.Client",
    ),
    "vscode": AppAlias(
        surface_forms=["vscode", "vs code", "visual studio code", "code"],
        manager="native",
        identifier="code",
        # Real Hyprland window class is "code", not the registry key "vscode" --
        # confirmed via `hyprctl clients -j` against a real running instance.
        window_class="code",
    ),
    "task_list": AppAlias(
        surface_forms=["task list", "taskwarrior", "task manager", "open tasks"],
        manager="native",
        identifier=(
            "kitty --class task-manager env HIDE_FETCH=1 zsh -c 'clear; task; exec zsh'"
        ),
    ),
    "timer_toggle": AppAlias(
        surface_forms=["start task", "start the last task", "toggle task", "toggle timer"],
        manager="native",
        identifier=str(Path.home() / ".scripts" / "task-toggle.sh"),
    ),
    "lock_screen": AppAlias(
        surface_forms=["lock screen", "lock my screen", "lock the screen"],
        manager="native",
        identifier="hyprlock",
    ),
    "whatsapp": AppAlias(
        # scanned as "whatsie" (the flatpak's own app name), but the user calls it
        # "whatsapp" by voice -- same identifier, an extra spoken name.
        surface_forms=[
            "whatsapp",
            "whatsie",
            "chatting",
            "chat",
            "i want to chat",
            "send message",
            "send a message",
            "i want to send a message",
            "i want to send message on whatsapp",
        ],
        manager="flatpak",
        identifier="com.ktechpit.whatsie",
    ),
    "antigravity": AppAlias(
        surface_forms=["antigravity"], manager="native", identifier="/usr/share/antigravity/antigravity"
    ),
    "postman": AppAlias(
        surface_forms=["postman"], manager="flatpak", identifier="com.getpostman.Postman"
    ),
    "screenshot": AppAlias(
        # Mirrors the user's real SUPER+D keybind exactly (screenshot -> swappy editor).
        # The `sh -c '...'` wrapper is part of the identifier itself (same pattern as
        # task_list's `zsh -c '...'` below) -- shlex.split() keeps it as one token, so
        # `sh` (not our own subprocess call) is what interprets the pipe/substitution.
        # Never shell=True on our side; the shell invocation is an explicit, visible,
        # developer-authored argv element, not something built from LLM/user text.
        surface_forms=["take a screenshot", "take screenshot", "screenshot"],
        manager="native",
        identifier="sh -c 'grim -g \"$(slurp)\" - | swappy -f -'",
    ),
    "screenshot_clipboard": AppAlias(
        # Mirrors the user's SUPER+O keybind (screenshot -> clipboard, no editor).
        surface_forms=["screenshot to clipboard", "copy a screenshot", "screenshot clipboard"],
        manager="native",
        identifier="sh -c 'grim -g \"$(slurp)\" - | wl-copy'",
    ),
    "screen_recording": AppAlias(
        # Mirrors the user's SUPER+CTRL+SHIFT+R keybind exactly (their own toggle script).
        surface_forms=["start screen recording", "toggle screen recording", "record my screen", "screen recording"],
        manager="native",
        identifier=f"{Path.home() / '.scripts' / 'screen-record.sh'} toggle",
    ),
}

DEFAULT_PACKAGES: dict[str, PackageAlias] = {
    "obsidian": PackageAlias(
        surface_forms=["obsidian"], manager="flatpak", identifier="md.obsidian.Obsidian"
    ),
    "vscode": PackageAlias(
        surface_forms=["vscode", "vs code", "visual studio code", "code"],
        manager="dnf",
        identifier="code",
    ),
}

# Real hyprctl dispatchers only (not `exec`-based launches, which live in DEFAULT_APPS
# above instead and reuse the OPEN_APP mechanism). Deliberately excludes `exit` (full
# session logout) -- too large a blast radius to leave un-gated; add it explicitly with
# requires_confirmation if you ever want it.
DEFAULT_HYPRLAND_ACTIONS: dict[str, HyprlandActionAlias] = {
    "close_window": HyprlandActionAlias(
        surface_forms=[
            "close this tile",
            "close this window",
            "close window",
            "close tile",
            "close this",
            "close it",
            "clean this tile",
            "clean this window",
            "shut this window",
            "shut this",
            "kill this window",
            "kill this",
            "get rid of this window",
        ],
        dispatcher="killactive",
    ),
    "toggle_floating": HyprlandActionAlias(
        surface_forms=["toggle floating", "make this floating", "float this window"],
        dispatcher="togglefloating",
    ),
    # Two distinct dispatches, matching this user's own SUPER+F / SUPER+SHIFT+F binds --
    # NOT synonyms. args="1" (maximize) keeps gaps/bar/curves, so on a workspace where the
    # window is already the sole tile it produces literally zero visible size/position
    # change (confirmed empirically: hyprctl clients showed identical [12,70]/[1896,998]
    # geometry before and after). args="0" (true fullscreen) goes edge-to-edge at full
    # monitor resolution, killing gaps/bar -- the dramatic, unambiguous effect "fullscreen"
    # colloquially implies. Previously conflated into one alias defaulting to args="1",
    # which is why "fullscreen this tile" looked like a no-op to the user despite the
    # dispatch reporting success.
    "maximize_window": HyprlandActionAlias(
        surface_forms=["maximize this", "maximize window", "maximize this window"],
        dispatcher="fullscreen",
        args="1",
    ),
    "fullscreen_window": HyprlandActionAlias(
        surface_forms=[
            "fullscreen this",
            "fullscreen this tile",
            "fullscreen this window",
            "full screen this",
            "make this fullscreen",
            "go fullscreen",
            "true fullscreen",
            "toggle fullscreen",
            "toggle the fullscreen",
            "toggle fullscreen of this tile",
            "toggle fullscreen for this window",
        ],
        dispatcher="fullscreen",
        args="0",
    ),
    "toggle_split": HyprlandActionAlias(
        surface_forms=["toggle split"],
        dispatcher="togglesplit",
    ),
    "toggle_scratchpad": HyprlandActionAlias(
        surface_forms=[
            "toggle scratchpad",
            "show scratchpad",
            "hide scratchpad",
            "open scratchpad",
            "close scratchpad",
        ],
        dispatcher="togglespecialworkspace",
        args="scratchpad",
    ),
}


def normalize_text(text: str) -> str:
    # Strips punctuation too, not just case/whitespace -- whisper's own punctuation choice
    # (a trailing period, in particular) isn't perfectly deterministic across two separate
    # recordings of "the same" spoken phrase, and this text feeds the Phase 4 LLM response
    # cache's key (llm/cache.py) as well as alias surface-form matching here. Without this,
    # "open a terminal." vs "open a terminal" would silently miss the cache despite being
    # the same command to a human ear.
    text = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(text.split())


def _resolve_alias(
    aliases: dict[str, AppAlias] | dict[str, PackageAlias] | dict[str, HyprlandActionAlias],
    spoken_name: str,
) -> tuple[str, AppAlias | PackageAlias | HyprlandActionAlias] | None:
    target = normalize_text(spoken_name)
    for key, alias in aliases.items():
        if target in (normalize_text(form) for form in alias.surface_forms):
            return key, alias
    return None


def _resolve_hyprland_action(
    aliases: dict[str, HyprlandActionAlias], spoken_name: str
) -> HyprlandActionAlias | None:
    # Free-text "name a WM action" is more open-ended than naming a specific app/package --
    # empirically the LLM sometimes emits its own slug (e.g. "toggle_floating") or a bare
    # word (e.g. "close", "fullscreen") instead of one of our exact surface forms. This
    # small, curated action space (~5 entries) makes substring-containment fallback low-risk,
    # unlike the open-ended app/package alias space where that would invite ambiguity.
    target = normalize_text(spoken_name.replace("_", " "))

    for alias in aliases.values():
        if target in (normalize_text(form) for form in alias.surface_forms):
            return alias

    for alias in aliases.values():
        for form in alias.surface_forms:
            normalized_form = normalize_text(form)
            if target and (target in normalized_form or normalized_form in target):
                return alias
    return None


class Config(BaseModel):
    confidence_threshold: float = 0.6
    terminal_cmd: list[str] = Field(default_factory=lambda: ["kitty"])
    file_manager_cmd: list[str] = Field(default_factory=lambda: ["nautilus"])
    allowed_roots: list[Path] = Field(default_factory=lambda: [Path.home()])
    model_en: str = "llama3.2:latest"
    ollama_base_url: str = "http://localhost:11434"
    llm_timeout_s: float = 60.0
    allowed_transcription_languages: list[str] = Field(default_factory=lambda: ["en", "ar"])
    apps: dict[str, AppAlias] = Field(default_factory=lambda: dict(DEFAULT_APPS))
    packages: dict[str, PackageAlias] = Field(default_factory=lambda: dict(DEFAULT_PACKAGES))
    hyprland_actions: dict[str, HyprlandActionAlias] = Field(
        default_factory=lambda: dict(DEFAULT_HYPRLAND_ACTIONS)
    )

    def resolve_app(self, spoken_name: str) -> AppAlias | None:
        result = _resolve_alias(self.apps, spoken_name)
        if result is None:
            return None
        alias = result[1]
        return alias if isinstance(alias, AppAlias) else None

    def resolve_app_window_class(self, spoken_name: str) -> str | None:
        """Best-effort Hyprland window `class` for a spoken app name -- the alias's
        explicit `window_class` if set, else the alias's own registry key as a fallback
        guess (correct for many simple apps, e.g. "spotify", but not guaranteed)."""
        result = _resolve_alias(self.apps, spoken_name)
        if result is None:
            return None
        key, alias = result
        if not isinstance(alias, AppAlias):
            return None
        return alias.window_class or key

    def resolve_package(self, spoken_name: str) -> PackageAlias | None:
        result = _resolve_alias(self.packages, spoken_name)
        if result is None:
            return None
        alias = result[1]
        return alias if isinstance(alias, PackageAlias) else None

    def resolve_hyprland_action(self, spoken_name: str) -> HyprlandActionAlias | None:
        return _resolve_hyprland_action(self.hyprland_actions, spoken_name)


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def config_path() -> Path:
    return _xdg_config_home() / "hypr-vocal-command" / "config.toml"


def generated_apps_path() -> Path:
    return config_path().parent / "apps.generated.toml"


def _load_alias_layer(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Path | None = None, generated_path: Path | None = None) -> Config:
    """Layers config in increasing priority: built-in defaults < apps.generated.toml
    (regenerated by `scan-apps`) < config.toml (hand-edited overrides)."""
    path = path or config_path()
    generated_path = generated_path or generated_apps_path()

    apps: dict[str, AppAlias] = dict(DEFAULT_APPS)
    packages: dict[str, PackageAlias] = dict(DEFAULT_PACKAGES)
    hyprland_actions: dict[str, HyprlandActionAlias] = dict(DEFAULT_HYPRLAND_ACTIONS)

    generated = _load_alias_layer(generated_path)
    apps.update({k: AppAlias(**v) for k, v in generated.get("apps", {}).items()})
    packages.update({k: PackageAlias(**v) for k, v in generated.get("packages", {}).items()})

    overrides = _load_alias_layer(path)
    apps.update({k: AppAlias(**v) for k, v in overrides.get("apps", {}).items()})
    packages.update({k: PackageAlias(**v) for k, v in overrides.get("packages", {}).items()})
    hyprland_actions.update(
        {k: HyprlandActionAlias(**v) for k, v in overrides.get("hyprland_actions", {}).items()}
    )

    scalar_overrides = {
        k: v for k, v in overrides.items() if k not in ("apps", "packages", "hyprland_actions")
    }

    return Config(
        apps=apps, packages=packages, hyprland_actions=hyprland_actions, **scalar_overrides
    )
