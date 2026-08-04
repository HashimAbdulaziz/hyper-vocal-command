from hypr_vocal_command.audio.vocabulary import build_command_vocabulary_prompt
from hypr_vocal_command.config import Config


def test_prompt_includes_hyprland_action_surface_forms():
    prompt = build_command_vocabulary_prompt(Config())
    assert "fullscreen this" in prompt
    assert "close this window" in prompt
    assert "toggle scratchpad" in prompt


def test_prompt_includes_generic_examples():
    prompt = build_command_vocabulary_prompt(Config())
    assert "open a terminal" in prompt
    assert "go to workspace two" in prompt


def test_prompt_has_no_duplicate_phrases():
    prompt = build_command_vocabulary_prompt(Config())
    phrases = [p for p in prompt.split(". ") if p]
    assert len(phrases) == len(set(phrases))


def test_prompt_includes_core_default_app_names():
    # Regression test: live testing showed "obsidian" repeatedly mistranscribed
    # ("save", "oxygen") with no app-name vocabulary primed at all.
    prompt = build_command_vocabulary_prompt(Config())
    assert "obsidian" in prompt
    assert "vscode" in prompt


def test_english_prompt_contains_no_arabic():
    # Whisper's context window is only 448 tokens, shared with decoded output. Emitting
    # every registered surface form regardless of language pushed this past 540 tokens,
    # and priming an English pass with Arabic text also biases the decoder's script.
    prompt = build_command_vocabulary_prompt(Config(), "en")
    assert not any("؀" <= ch <= "ۿ" for ch in prompt)


def test_arabic_prompt_contains_arabic_and_stays_small():
    prompt = build_command_vocabulary_prompt(Config(), "ar")
    assert "الواتس" in prompt
    assert "سبوتيفاي" in prompt
    # Egyptian Arabic is heavily code-switched, so core English app names stay primed too.
    assert "spotify" in prompt
    assert len(prompt) // 4 < 448


def test_prompt_does_not_include_the_full_scanned_app_catalog():
    # Deliberately bounded: config.apps can hold 100+ scanned apps, which would blow
    # whisper's small context window if all crammed into the prompt.
    from hypr_vocal_command.config import AppAlias

    config = Config()
    config.apps["some_random_scanned_app"] = AppAlias(
        surface_forms=["some random scanned app"], manager="native", identifier="foo"
    )
    prompt = build_command_vocabulary_prompt(config)
    assert "some random scanned app" not in prompt
