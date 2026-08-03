"""Direct handler tests (bypassing the executor's confirmation gate, which always blocks
UPDATE_SYSTEM until Phase 10 -- see test_executor.py for that gating behavior).
"""

import subprocess

from hypr_vocal_command.config import Config
from hypr_vocal_command.handlers.update_system import UpdateSystemArgs, update_system


def test_scope_dnf_only_calls_dnf(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = update_system(UpdateSystemArgs(scope="dnf"), Config())

    assert result.ok is True
    assert calls == [["sudo", "-n", "/usr/bin/dnf", "update", "-y"]]


def test_scope_flatpak_only_calls_flatpak(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = update_system(UpdateSystemArgs(scope="flatpak"), Config())

    assert result.ok is True
    assert calls == [["flatpak", "update", "-y"]]


def test_scope_all_calls_both(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = update_system(UpdateSystemArgs(scope="all"), Config())

    assert result.ok is True
    assert calls == [
        ["sudo", "-n", "/usr/bin/dnf", "update", "-y"],
        ["flatpak", "update", "-y"],
    ]


def test_dnf_failure_is_reported(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no sudoers rule")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = update_system(UpdateSystemArgs(scope="dnf"), Config())

    assert result.ok is False
    assert "no sudoers rule" in result.message
