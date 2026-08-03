"""MEDIA_CONTROL: play/pause/toggle music playback.

Targets Spotify specifically via `playerctl -p spotify`, the standard Linux MPRIS
media-control CLI -- deliberately not the ambiguous "whatever player is currently
active" default (`playerctl play` with no `-p`), since an unrelated Chrome tab with
any paused/playing media also registers its own MPRIS session and would be a
confusing, surprising target for a command the user framed entirely around Spotify.

"play" is deliberately smarter than a bare `playerctl play`: if Spotify isn't running
at all, there's nothing to resume, so it launches the app instead -- matching how the
user actually talks about this ("play music" should just make music happen, regardless
of whether Spotify was already open). "pause" only ever pauses; it never launches
anything, since there's nothing to pause if Spotify isn't running.

"toggle" is for the bare word "music" with no explicit play/pause/stop/resume verb --
open Spotify if it isn't running, otherwise flip whichever state it's actually in
(checked via `playerctl status`, not guessed).
"""

import subprocess
from typing import Literal

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler

_SPOTIFY_FLATPAK_ID = "com.spotify.Client"


class MediaControlArgs(BaseModel):
    action: Literal["play", "pause", "toggle"]


def _spotify_status() -> str | None:
    """playerctl's status string ("Playing"/"Paused") if Spotify is running as an
    MPRIS player, or None if it isn't running at all."""
    result = subprocess.run(
        ["playerctl", "-p", "spotify", "status"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _launch_spotify() -> ExecutionResult:
    subprocess.Popen(
        ["flatpak", "run", _SPOTIFY_FLATPAK_ID],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return ExecutionResult(ok=True, message="Spotify wasn't running -- launched it.")


def _resume() -> ExecutionResult:
    result = subprocess.run(
        ["playerctl", "-p", "spotify", "play"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return ExecutionResult(
            ok=False, message=f"Failed to resume Spotify: {result.stderr.strip()[:200]}"
        )
    return ExecutionResult(ok=True, message="Resumed Spotify playback.")


def _pause() -> ExecutionResult:
    result = subprocess.run(
        ["playerctl", "-p", "spotify", "pause"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return ExecutionResult(ok=False, message="Nothing is playing on Spotify.")
    return ExecutionResult(ok=True, message="Paused Spotify.")


@intent_handler(
    "MEDIA_CONTROL",
    MediaControlArgs,
    description=(
        "Control music playback: 'play' (resume, or launch Spotify if it isn't running "
        "yet), 'pause'/'stop', or 'toggle' (only when no explicit play/pause verb is "
        "given -- e.g. the bare word 'music' alone, meaning flip whatever state it's "
        "currently in). Use for phrases like 'play music', 'pause music', 'stop music', "
        "'resume music', 'music'. NOT for opening Spotify by name with no playback "
        "intent (use OPEN_APP{app_name:'spotify'} for that)."
    ),
)
def media_control(args: MediaControlArgs, config: Config) -> ExecutionResult:
    if args.action == "pause":
        return _pause()

    status = _spotify_status()
    if status is None:
        return _launch_spotify()

    if args.action == "toggle" and status == "Playing":
        return _pause()

    return _resume()
