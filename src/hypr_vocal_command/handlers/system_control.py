"""SYSTEM_CONTROL: audio volume, microphone mute, and screen brightness.

Mirrors this machine's own XF86 media-key bindings exactly (`wpctl` for audio, matching
the `XF86AudioRaiseVolume`/`XF86AudioMute`/`XF86AudioMicMute` binds; `brightnessctl -e4
-n2` for backlight, matching `XF86MonBrightnessUp`/`Down`) rather than inventing a
different mechanism for the same job -- so a voice command and the physical key produce
identical results, including the same 5% step size.

`action` is deliberately ONE flat enum rather than a (target, direction) pair. A pair
makes nonsense combinations like "mute the brightness" representable, which the grammar
would happily emit and the handler would then have to reject at runtime; a flat enum
makes them unrepresentable in the schema itself. This is the same lesson as Phase 3's
`intent` finding -- constrain it in the grammar, don't validate it after the fact.

Volume raising is capped with `-l 1` (100%), copied from the real keybind: PipeWire will
otherwise happily amplify past 100% into distortion.
"""

import subprocess
from typing import Literal

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler

_SINK = "@DEFAULT_AUDIO_SINK@"
_SOURCE = "@DEFAULT_AUDIO_SOURCE@"
_STEP = "5%"

# argv lists, never shell strings -- same rule as every other handler here.
_COMMANDS: dict[str, tuple[list[str], str]] = {
    "volume_up": (["wpctl", "set-volume", "-l", "1", _SINK, f"{_STEP}+"], "Volume up."),
    "volume_down": (["wpctl", "set-volume", _SINK, f"{_STEP}-"], "Volume down."),
    "volume_mute": (["wpctl", "set-mute", _SINK, "toggle"], "Toggled mute."),
    "mic_mute": (["wpctl", "set-mute", _SOURCE, "toggle"], "Toggled microphone mute."),
    "brightness_up": (["brightnessctl", "-e4", "-n2", "set", f"{_STEP}+"], "Brightness up."),
    "brightness_down": (["brightnessctl", "-e4", "-n2", "set", f"{_STEP}-"], "Brightness down."),
}


class SystemControlArgs(BaseModel):
    action: Literal[
        "volume_up",
        "volume_down",
        "volume_mute",
        "mic_mute",
        "brightness_up",
        "brightness_down",
    ]


@intent_handler(
    "SYSTEM_CONTROL",
    SystemControlArgs,
    description=(
        "Adjust system audio volume, microphone mute, or screen brightness. `action` is "
        "one of 'volume_up', 'volume_down', 'volume_mute' (also for unmute -- it "
        "toggles), 'mic_mute', 'brightness_up', 'brightness_down'. Use for 'turn the "
        "volume up', 'louder', 'mute', 'mute my mic', 'brighter', 'dim the screen'. NOT "
        "for music playback control such as play/pause/skip (use MEDIA_CONTROL), and "
        "NOT for anything to do with windows or workspaces."
    ),
)
def system_control(args: SystemControlArgs, config: Config) -> ExecutionResult:
    cmd, message = _COMMANDS[args.action]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"{args.action} failed: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message=message)
