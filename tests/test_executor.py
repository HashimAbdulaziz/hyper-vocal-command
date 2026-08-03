import json
import subprocess

import pytest

from hypr_vocal_command import handlers  # noqa: F401  (populates the registry)
from hypr_vocal_command.config import Config
from hypr_vocal_command.executor import execute


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch, tmp_path):
    # Never send real desktop notifications or write to the real state dir during tests.
    monkeypatch.setattr("hypr_vocal_command.executor.notify", lambda *a, **k: None)
    monkeypatch.setattr("hypr_vocal_command.utils.telemetry._state_dir", lambda: tmp_path)


def test_open_terminal_executes_when_confident(monkeypatch, config):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = execute(
        {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.95, "args": {}},
        config=config,
    )

    assert result.ok is True
    assert captured["cmd"] == config.terminal_cmd


def test_low_confidence_blocks_execution(monkeypatch, config):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("should not be called"))

    result = execute(
        {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.1, "args": {}},
        config=config,
    )

    assert result.ok is False
    assert "confidence" in result.message.lower()


def test_update_package_always_blocked_pending_confirmation_flow(monkeypatch, config):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("should not be called"))

    result = execute(
        {
            "schema_version": 1,
            "intent": "UPDATE_PACKAGE",
            "confidence": 0.99,
            "args": {"package_name": "vscode"},
        },
        config=config,
    )

    assert result.ok is False
    assert "confirmation" in result.message.lower()


def test_update_system_always_blocked_pending_confirmation_flow(monkeypatch, config):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("should not be called"))

    result = execute(
        {
            "schema_version": 1,
            "intent": "UPDATE_SYSTEM",
            "confidence": 0.99,
            "args": {"scope": "dnf"},
        },
        config=config,
    )

    assert result.ok is False
    assert "confirmation" in result.message.lower()


def test_unrecognized_intent_is_notify_only(monkeypatch, config):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("should not be called"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("should not be called"))

    result = execute(
        {"schema_version": 1, "intent": "UNRECOGNIZED", "confidence": 0.9, "args": {}},
        config=config,
    )

    assert result.ok is False


def test_invalid_payload_is_handled_gracefully(config):
    result = execute({"not": "a valid envelope"}, config=config)
    assert result.ok is False


def test_open_app_resolves_alias_and_launches(monkeypatch, config):
    monkeypatch.setattr(
        "hypr_vocal_command.handlers.open_app.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = execute(
        {
            "schema_version": 1,
            "intent": "OPEN_APP",
            "confidence": 0.9,
            "args": {"app_name": "vs code"},
        },
        config=config,
    )

    assert result.ok is True
    assert captured["cmd"] == ["/usr/bin/code"]


def test_open_app_unknown_app_returns_failure(config):
    result = execute(
        {
            "schema_version": 1,
            "intent": "OPEN_APP",
            "confidence": 0.9,
            "args": {"app_name": "some totally unknown app"},
        },
        config=config,
    )
    assert result.ok is False


def test_workspace_switch_executes_when_confident(monkeypatch, config):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    result = execute(
        {
            "schema_version": 1,
            "intent": "WORKSPACE_SWITCH",
            "confidence": 0.95,
            "args": {"workspace": 2},
        },
        config=config,
    )

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "workspace", "2"]]


def test_hyprland_action_executes_when_confident(monkeypatch, config):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    result = execute(
        {
            "schema_version": 1,
            "intent": "HYPRLAND_ACTION",
            "confidence": 0.95,
            "args": {"action": "close this window"},
        },
        config=config,
    )

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "killactive"]]


def test_llm_context_is_threaded_into_telemetry(monkeypatch, config, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: object())

    execute(
        {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.95, "args": {}},
        config=config,
        raw_llm_response='{"intent": "OPEN_TERMINAL"}',
        llm_latency_ms=1234.5,
    )

    events_path = tmp_path / "events.jsonl"
    last_event = json.loads(events_path.read_text().strip().splitlines()[-1])
    assert last_event["raw_llm_response"] == '{"intent": "OPEN_TERMINAL"}'
    assert last_event["llm_latency_ms"] == 1234.5


def test_transcript_is_threaded_into_telemetry(monkeypatch, config, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: object())

    execute(
        {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.95, "args": {}},
        config=config,
        transcript="open a terminal",
    )

    events_path = tmp_path / "events.jsonl"
    last_event = json.loads(events_path.read_text().strip().splitlines()[-1])
    assert last_event["transcript"] == "open a terminal"
