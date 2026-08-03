import subprocess

from hypr_vocal_command.config import Config
from hypr_vocal_command.handlers.media_control import MediaControlArgs, media_control


def test_pause_dispatches_to_spotify_player(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = media_control(MediaControlArgs(action="pause"), Config())

    assert result.ok is True
    assert calls == [["playerctl", "-p", "spotify", "pause"]]


def test_pause_reports_failure_when_nothing_is_playing(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No players found"),
    )

    result = media_control(MediaControlArgs(action="pause"), Config())

    assert result.ok is False
    assert "Nothing is playing" in result.message


def test_play_resumes_when_spotify_is_already_running(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest_fail_if_called())

    result = media_control(MediaControlArgs(action="play"), Config())

    assert result.ok is True
    assert result.message == "Resumed Spotify playback."
    # first call checks status, second call resumes playback -- both target spotify
    assert calls == [
        ["playerctl", "-p", "spotify", "status"],
        ["playerctl", "-p", "spotify", "play"],
    ]


def test_play_launches_spotify_when_not_already_running(monkeypatch):
    status_calls = []

    def fake_run(cmd, **kwargs):
        status_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No players found")

    launched = {}

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        return object()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = media_control(MediaControlArgs(action="play"), Config())

    assert result.ok is True
    assert "launched it" in result.message
    assert launched["cmd"] == ["flatpak", "run", "com.spotify.Client"]
    # only the status check should have run playerctl -- never a bare "play" against
    # a nonexistent player once we already know it's not running
    assert status_calls == [["playerctl", "-p", "spotify", "status"]]


def pytest_fail_if_called():
    raise AssertionError("Popen should not be called on the resume path")


def test_toggle_launches_spotify_when_not_running(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No players found"),
    )
    launched = {}
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **k: launched.setdefault("cmd", cmd) or object()
    )

    result = media_control(MediaControlArgs(action="toggle"), Config())

    assert result.ok is True
    assert launched["cmd"] == ["flatpak", "run", "com.spotify.Client"]


def test_toggle_pauses_when_currently_playing(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "status":
            return subprocess.CompletedProcess(cmd, 0, stdout="Playing\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = media_control(MediaControlArgs(action="toggle"), Config())

    assert result.ok is True
    assert result.message == "Paused Spotify."
    assert calls == [
        ["playerctl", "-p", "spotify", "status"],
        ["playerctl", "-p", "spotify", "pause"],
    ]


def test_toggle_resumes_when_currently_paused(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "status":
            return subprocess.CompletedProcess(cmd, 0, stdout="Paused\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = media_control(MediaControlArgs(action="toggle"), Config())

    assert result.ok is True
    assert result.message == "Resumed Spotify playback."
    assert calls == [
        ["playerctl", "-p", "spotify", "status"],
        ["playerctl", "-p", "spotify", "play"],
    ]
