import pytest
from pydantic import BaseModel

from hypr_vocal_command import handlers
from hypr_vocal_command.config import Config
from hypr_vocal_command.registry import REGISTRY, ExecutionResult, intent_handler, validate_startup


class _FakeArgs(BaseModel):
    pass


def test_intent_handler_registers_into_registry():
    name = "TEST_FAKE_INTENT_REGISTERS"
    assert name not in REGISTRY
    try:

        @intent_handler(name, _FakeArgs)
        def _fake(args: _FakeArgs, config: Config) -> ExecutionResult:
            return ExecutionResult(ok=True, message="fake")

        assert name in REGISTRY
        assert REGISTRY[name].args_model is _FakeArgs
        assert REGISTRY[name].requires_confirmation is False
    finally:
        REGISTRY.pop(name, None)


def test_duplicate_registration_raises():
    name = "TEST_FAKE_INTENT_DUPLICATE"
    try:

        @intent_handler(name, _FakeArgs)
        def _fake(args: _FakeArgs, config: Config) -> ExecutionResult:
            return ExecutionResult(ok=True, message="fake")

        with pytest.raises(RuntimeError):

            @intent_handler(name, _FakeArgs)
            def _fake2(args: _FakeArgs, config: Config) -> ExecutionResult:
                return ExecutionResult(ok=True, message="fake2")
    finally:
        REGISTRY.pop(name, None)


def test_validate_startup_raises_if_handler_missing():
    with pytest.raises(RuntimeError):
        validate_startup(["SOME_INTENT_THAT_WAS_NEVER_REGISTERED"])


def test_validate_startup_passes_for_registered_intents():
    validate_startup(handlers.EXPECTED_INTENTS)
