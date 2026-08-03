import pytest
from pydantic import ValidationError

from hypr_vocal_command import handlers  # noqa: F401  (populates the registry)
from hypr_vocal_command.schema import parse_envelope


def test_valid_open_terminal_envelope_parses():
    envelope = parse_envelope(
        {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.95, "args": {}}
    )
    assert envelope.intent == "OPEN_TERMINAL"
    assert envelope.confidence == 0.95


def test_unknown_intent_is_rejected():
    with pytest.raises(ValidationError):
        parse_envelope(
            {"schema_version": 1, "intent": "DELETE_EVERYTHING", "confidence": 0.9, "args": {}}
        )


def test_wrong_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        parse_envelope(
            {"schema_version": 2, "intent": "OPEN_TERMINAL", "confidence": 0.9, "args": {}}
        )


def test_missing_schema_version_is_rejected():
    # schema_version is deliberately excluded from the schema the LLM generates against
    # (envelope_json_schema()) and injected by the LLM client afterward instead -- but
    # parse_envelope()'s own full validation must still require it, for any other caller
    # that builds a raw envelope dict by hand (debug-execute, tests, etc).
    with pytest.raises(ValidationError):
        parse_envelope({"intent": "OPEN_TERMINAL", "confidence": 0.9, "args": {}})


def test_envelope_json_schema_omits_schema_version_but_requires_intent():
    from hypr_vocal_command.schema import envelope_json_schema

    schema = envelope_json_schema()
    for variant in schema["$defs"].values():
        if "intent" in variant.get("properties", {}):
            assert "intent" in variant["required"]
            assert "schema_version" not in variant["properties"]


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        parse_envelope(
            {"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 1.5, "args": {}}
        )


def test_open_app_requires_app_name_arg():
    with pytest.raises(ValidationError):
        parse_envelope(
            {"schema_version": 1, "intent": "OPEN_APP", "confidence": 0.9, "args": {}}
        )
