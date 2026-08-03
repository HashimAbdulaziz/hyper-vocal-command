from hypr_vocal_command import handlers  # noqa: F401  (populates the registry)
from hypr_vocal_command.llm.prompts import build_system_prompt
from hypr_vocal_command.registry import REGISTRY


def test_system_prompt_mentions_every_registered_intent():
    prompt = build_system_prompt()
    for name in REGISTRY:
        assert name in prompt


def test_system_prompt_includes_disambiguation_guidance():
    prompt = build_system_prompt()
    assert "never OPEN_APP for this" in prompt
