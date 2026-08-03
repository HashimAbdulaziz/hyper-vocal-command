"""Side-effect imports so every intent handler registers itself into the registry at startup."""

from . import (  # noqa: F401
    close_app,
    hyprland_action,
    media_control,
    open_app,
    open_file_manager,
    open_terminal,
    unrecognized,
    update_package,
    update_system,
    workspace_switch,
)

EXPECTED_INTENTS = (
    "OPEN_TERMINAL",
    "OPEN_FILE_MANAGER",
    "OPEN_APP",
    "UPDATE_PACKAGE",
    "UPDATE_SYSTEM",
    "WORKSPACE_SWITCH",
    "HYPRLAND_ACTION",
    "MEDIA_CONTROL",
    "CLOSE_APP",
    "UNRECOGNIZED",
)
