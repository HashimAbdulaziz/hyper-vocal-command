import subprocess

import pytest

from hypr_vocal_command.config import Config
from hypr_vocal_command.handlers.media_control import MediaControlArgs, media_control
from hypr_vocal_command.handlers.move_to_workspace import (
    MoveToWorkspaceArgs,
    move_to_workspace,
)
from hypr_vocal_command.handlers.system_control import SystemControlArgs, system_control


@pytest.fixture
def calls(monkeypatch):
    recorded: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return recorded


def test_volume_up_caps_at_100_percent(calls):
    # `-l 1` mirrors the real XF86AudioRaiseVolume bind: without it PipeWire amplifies
    # past 100% into distortion.
    result = system_control(SystemControlArgs(action="volume_up"), Config())
    assert result.ok is True
    assert calls == [["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "5%+"]]


def test_volume_down_does_not_pass_the_cap(calls):
    system_control(SystemControlArgs(action="volume_down"), Config())
    assert calls == [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]]


def test_mute_targets_the_sink_and_mic_mute_targets_the_source(calls):
    # Muting the speakers and muting the microphone are different devices entirely --
    # mixing them up would leave a call unmuted while silencing playback, or vice versa.
    system_control(SystemControlArgs(action="volume_mute"), Config())
    system_control(SystemControlArgs(action="mic_mute"), Config())
    assert calls == [
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
    ]


def test_brightness_uses_the_same_flags_as_the_real_keybind(calls):
    system_control(SystemControlArgs(action="brightness_up"), Config())
    assert calls == [["brightnessctl", "-e4", "-n2", "set", "5%+"]]


def test_system_control_reports_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "no backlight device"),
    )
    result = system_control(SystemControlArgs(action="brightness_up"), Config())
    assert result.ok is False
    assert "no backlight device" in result.message


def test_invalid_action_is_unrepresentable():
    # The flat enum is what makes "mute the brightness" impossible to express at all,
    # rather than something the handler has to detect and reject at runtime.
    with pytest.raises(ValueError):
        SystemControlArgs(action="brightness_mute")


def test_track_skip_dispatches_playerctl(calls):
    assert media_control(MediaControlArgs(action="next"), Config()).ok is True
    assert media_control(MediaControlArgs(action="previous"), Config()).ok is True
    assert calls == [
        ["playerctl", "-p", "spotify", "next"],
        ["playerctl", "-p", "spotify", "previous"],
    ]


def test_track_skip_never_launches_spotify(monkeypatch):
    # Unlike "play", skipping presupposes something is already playing -- launching the
    # app in response to "next track" would be a surprising outcome.
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: launched.append(a))
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "no players")
    )

    result = media_control(MediaControlArgs(action="next"), Config())

    assert result.ok is False
    assert launched == []


def test_move_to_workspace_dispatches_movetoworkspace(calls):
    result = move_to_workspace(MoveToWorkspaceArgs(workspace=3), Config())
    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "movetoworkspace", "3"]]


def test_move_to_workspace_rejects_out_of_range():
    with pytest.raises(ValueError):
        MoveToWorkspaceArgs(workspace=0)
    with pytest.raises(ValueError):
        MoveToWorkspaceArgs(workspace=200)
