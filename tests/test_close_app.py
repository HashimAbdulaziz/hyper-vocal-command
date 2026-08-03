import subprocess

from hypr_vocal_command.config import Config
from hypr_vocal_command.handlers.close_app import CloseAppArgs, close_app


def test_close_app_dispatches_class_selector(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = close_app(CloseAppArgs(app_name="spotify"), Config())

    assert result.ok is True
    assert result.message == "Closed spotify."
    assert calls == [["hyprctl", "dispatch", "closewindow", "class:^(spotify)$"]]


def test_close_app_uses_explicit_window_class_override(monkeypatch):
    # vscode's registry key is "vscode" but its real Hyprland class is "code" --
    # confirmed via a real running instance and set explicitly in config.py.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = close_app(CloseAppArgs(app_name="vscode"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "closewindow", "class:^(code)$"]]


def test_close_app_reports_failure_when_no_window_found(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(
            cmd, 0, stdout="closeWindow: no window found\n", stderr=""
        ),
    )

    result = close_app(CloseAppArgs(app_name="spotify"), Config())

    assert result.ok is False
    assert "isn't currently open" in result.message


def test_close_app_unknown_app_returns_failure():
    result = close_app(CloseAppArgs(app_name="some totally unknown app"), Config())
    assert result.ok is False
