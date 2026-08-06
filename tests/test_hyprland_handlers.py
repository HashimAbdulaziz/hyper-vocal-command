import subprocess

from hypr_vocal_command.config import Config
from hypr_vocal_command.handlers.hyprland_action import HyprlandActionArgs, hyprland_action
from hypr_vocal_command.handlers.workspace_switch import WorkspaceSwitchArgs, workspace_switch


def test_workspace_switch_dispatches_correct_number(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = workspace_switch(WorkspaceSwitchArgs(workspace=2), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "workspace", "2"]]


def test_workspace_switch_reports_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such monitor")
    )

    result = workspace_switch(WorkspaceSwitchArgs(workspace=99), Config())

    assert result.ok is False
    assert "no such monitor" in result.message


def test_workspace_switch_next_dispatches_relative_arg(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    result = workspace_switch(WorkspaceSwitchArgs(workspace="next"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "workspace", "+1"]]


def test_workspace_switch_previous_dispatches_relative_arg(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    result = workspace_switch(WorkspaceSwitchArgs(workspace="previous"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "workspace", "previous"]]


def test_hyprland_action_close_window_resolves_and_dispatches(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = hyprland_action(HyprlandActionArgs(action="close this tile"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "killactive"]]


def test_hyprland_action_with_args_includes_them(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = hyprland_action(HyprlandActionArgs(action="toggle scratchpad"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "togglespecialworkspace", "scratchpad"]]


def test_hyprland_action_scratchpad_resolves_regardless_of_show_hide_toggle_wording(monkeypatch):
    # Regression test: live testing showed "hide scratchpad" classified correctly as
    # HYPRLAND_ACTION but failed alias resolution, since the dispatcher is a toggle and
    # "hide"/"show"/"toggle" all map to the same call -- all three wordings must resolve.
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", "")
    )

    for phrase in ("show scratchpad", "hide scratchpad", "toggle scratchpad"):
        result = hyprland_action(HyprlandActionArgs(action=phrase), Config())
        assert result.ok is True, phrase


def test_close_window_resolves_common_synonyms(monkeypatch):
    # Regression test: live testing showed the LLM preserves colloquial phrasing rather
    # than normalizing it, and "close it"/"shut this window"/"kill this window" shared no
    # text with our registered surface forms, so they classified correctly but failed to
    # resolve to killactive.
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", "")
    )

    for phrase in ("close it", "shut this window", "kill this window"):
        result = hyprland_action(HyprlandActionArgs(action=phrase), Config())
        assert result.ok is True, phrase


def test_close_window_resolves_clean_close_stt_confusion(monkeypatch):
    # Regression test: real STT output rendered "close this tile" as "clean this tile"
    # (close/clean confusion) -- must still resolve to killactive.
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", "")
    )

    for phrase in ("clean this tile", "clean this window"):
        result = hyprland_action(HyprlandActionArgs(action=phrase), Config())
        assert result.ok is True, phrase


def test_hyprland_action_unknown_action_returns_failure():
    result = hyprland_action(HyprlandActionArgs(action="do a backflip"), Config())
    assert result.ok is False


def test_hyprland_action_tolerates_llm_invented_slugs_and_bare_words(monkeypatch):
    # Regression test: live testing showed the LLM sometimes emits its own slug
    # ("toggle_floating") or a bare word ("fullscreen", "close") instead of one of our
    # exact surface forms -- resolution must still succeed for these.
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "", "")
    )

    assert hyprland_action(HyprlandActionArgs(action="toggle_floating"), Config()).ok is True
    assert hyprland_action(HyprlandActionArgs(action="fullscreen"), Config()).ok is True
    assert hyprland_action(HyprlandActionArgs(action="close"), Config()).ok is True


def _fake_run_with_active_window(calls, active: dict | None):
    """subprocess.run stub that answers `hyprctl activewindow -j` with `active` and
    records every other dispatch into `calls`."""
    import json as _json

    def fake_run(cmd, **kwargs):
        if "activewindow" in cmd:
            return subprocess.CompletedProcess(cmd, 0, _json.dumps(active or {}), "")
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    return fake_run


def test_chrome_tab_action_targets_the_focused_window_by_address(monkeypatch):
    # With several Chrome windows open, a bare class selector acts on whichever one
    # Hyprland returns first -- which may not be the one in front of the user. The tab
    # actions must address the FOCUSED window explicitly.
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_with_active_window(
            calls, {"class": "google-chrome", "address": "0xdeadbeef"}
        ),
    )

    result = hyprland_action(HyprlandActionArgs(action="close this tab"), Config())

    assert result.ok is True
    assert calls == [["hyprctl", "dispatch", "sendshortcut", "CTRL,W,address:0xdeadbeef"]]


def test_chrome_tab_action_refuses_when_chrome_is_not_focused(monkeypatch):
    # Refusing is the safe outcome: firing Ctrl+W at some other Chrome window would
    # destroy a page the user never looked at, while appearing to succeed.
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_with_active_window(calls, {"class": "code", "address": "0xabc"}),
    )

    result = hyprland_action(HyprlandActionArgs(action="close this tab"), Config())

    assert result.ok is False
    assert "focused" in result.message
    assert calls == []  # nothing dispatched at all


def test_chrome_tab_action_refuses_when_nothing_is_focused(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run_with_active_window(calls, {}))

    result = hyprland_action(HyprlandActionArgs(action="new tab"), Config())

    assert result.ok is False
    assert calls == []


def test_plain_window_actions_do_not_query_the_active_window(monkeypatch):
    # Only aliases with target_active_class pay for the extra hyprctl round-trip;
    # killactive and friends already act on the focused window implicitly.
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert hyprland_action(HyprlandActionArgs(action="close this window"), Config()).ok
    assert seen == [["hyprctl", "dispatch", "killactive"]]
