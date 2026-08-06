import json

from hypr_vocal_command.review import (
    CommandRecord,
    _flag_records,
    build_report,
    load_command_records,
    review,
)


def _write_events(path, events):
    with path.open("w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def test_load_command_records_skips_connection_noise_and_missing_transcript(tmp_path):
    path = tmp_path / "events.jsonl"
    _write_events(
        path,
        [
            {"timestamp": 1.0, "stage": "connection", "reason": "client_disconnected_before_response"},
            {"timestamp": 2.0, "stage": "execute", "intent": "OPEN_TERMINAL", "ok": True},  # no transcript -- pre-pipeline debug-execute call
            {
                "timestamp": 3.0,
                "stage": "execute",
                "intent": "OPEN_TERMINAL",
                "confidence": 0.95,
                "ok": True,
                "message": "Opened terminal (kitty).",
                "transcript": "open a terminal",
                "language": "en",
                "args": {},
            },
        ],
    )

    records = load_command_records(path)

    assert len(records) == 1
    assert records[0].transcript == "open a terminal"
    assert records[0].language == "en"


def test_load_command_records_respects_since_cutoff(tmp_path):
    path = tmp_path / "events.jsonl"
    _write_events(
        path,
        [
            {"timestamp": 100.0, "stage": "execute", "transcript": "old command", "ok": True},
            {"timestamp": 200.0, "stage": "execute", "transcript": "recent command", "ok": True},
        ],
    )

    records = load_command_records(path, since=150.0)

    assert [r.transcript for r in records] == ["recent command"]


def test_load_command_records_tolerates_a_corrupt_line(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"timestamp": 1.0, "stage": "execute", "transcript": "ok one", "ok": true}\n'
        "not valid json at all\n"
        '{"timestamp": 2.0, "stage": "execute", "transcript": "ok two", "ok": true}\n'
    )

    records = load_command_records(path)

    assert [r.transcript for r in records] == ["ok one", "ok two"]


def test_load_command_records_returns_empty_for_missing_file(tmp_path):
    assert load_command_records(tmp_path / "does-not-exist.jsonl") == []


def test_records_sorted_chronologically_even_if_file_is_not(tmp_path):
    path = tmp_path / "events.jsonl"
    _write_events(
        path,
        [
            {"timestamp": 50.0, "stage": "execute", "transcript": "second", "ok": True},
            {"timestamp": 10.0, "stage": "execute", "transcript": "first", "ok": True},
        ],
    )

    records = load_command_records(path)

    assert [r.transcript for r in records] == ["first", "second"]


def _record(**overrides) -> CommandRecord:
    base = {
        "timestamp": 1.0,
        "stage": "execute",
        "language": "en",
        "transcript": "open obsidian",
        "intent": "OPEN_APP",
        "confidence": 0.9,
        "ok": True,
        "message": "Opened obsidian.",
        "args": {"app_name": "obsidian"},
    }
    base.update(overrides)
    return CommandRecord(**base)


def test_blocked_flag_applies_to_non_ok_records():
    records = _flag_records([_record(ok=False, message="Unknown app")], confidence_threshold=0.6)
    assert records[0].flags == ("blocked",)


def test_low_margin_pass_flag_for_a_confidence_just_above_threshold():
    records = _flag_records([_record(ok=True, confidence=0.62)], confidence_threshold=0.6)
    assert "low-margin-pass" in records[0].flags


def test_no_low_margin_flag_for_a_comfortably_high_confidence():
    records = _flag_records([_record(ok=True, confidence=0.95)], confidence_threshold=0.6)
    assert records[0].flags == ()


def test_inconsistent_flag_when_same_transcript_gets_different_intents():
    records = _flag_records(
        [
            _record(transcript="close spotify", intent="CLOSE_APP", confidence=0.9),
            _record(transcript="close spotify", intent="HYPRLAND_ACTION", confidence=0.9),
        ],
        confidence_threshold=0.6,
    )
    assert all("inconsistent" in r.flags for r in records)


def test_no_inconsistent_flag_for_orthographic_variants_that_normalize_the_same():
    # "open a terminal." / "open a terminal" must be recognized as the same command
    # (normalize_text strips punctuation) -- not falsely flagged as instability.
    records = _flag_records(
        [
            _record(transcript="open a terminal.", intent="OPEN_TERMINAL"),
            _record(transcript="open a terminal", intent="OPEN_TERMINAL"),
        ],
        confidence_threshold=0.6,
    )
    assert all("inconsistent" not in r.flags for r in records)


def test_build_report_includes_ok_true_rows_not_just_failures():
    # The core design requirement: the two most dangerous bugs found in this project
    # logged ok=true, so a report that only lists failures would hide the worst cases.
    report = build_report([_record(ok=True, transcript="a clean success")])
    assert "a clean success" in report
    assert "ok=True" in report


def test_build_report_on_empty_input():
    assert "No commands" in build_report([])


def test_review_end_to_end(tmp_path):
    path = tmp_path / "events.jsonl"
    _write_events(
        path,
        [
            {
                "timestamp": 1.0,
                "stage": "execute",
                "transcript": "open obsidian",
                "intent": "OPEN_APP",
                "confidence": 0.95,
                "ok": True,
                "message": "Opened obsidian.",
                "args": {"app_name": "obsidian"},
                "language": "en",
            },
            {
                "timestamp": 2.0,
                "stage": "gate",
                "transcript": "garbled nonsense",
                "intent": "UNRECOGNIZED",
                "confidence": 0.2,
                "ok": False,
                "reason": "low_confidence",
                "language": "en",
            },
        ],
    )

    report = review(path=path, confidence_threshold=0.6)

    assert "2 commands" in report
    assert "open obsidian" in report
    assert "garbled nonsense" in report
    assert "[blocked]" in report
