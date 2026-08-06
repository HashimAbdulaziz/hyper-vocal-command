"""Side-effect imports so every intent handler registers itself into the registry at startup."""

from . import (  # noqa: F401
    close_app,
    hyprland_action,
    media_control,
    move_to_workspace,
    open_app,
    open_file_manager,
    open_terminal,
    system_control,
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
    "MOVE_TO_WORKSPACE",
    "HYPRLAND_ACTION",
    "MEDIA_CONTROL",
    "SYSTEM_CONTROL",
    "CLOSE_APP",
    "UNRECOGNIZED",
)
