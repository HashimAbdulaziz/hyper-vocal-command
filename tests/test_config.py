from hypr_vocal_command.appscan import AppEntry, write_generated_apps
from hypr_vocal_command.config import load_config, normalize_text


def test_normalize_text_strips_punctuation():
    # Regression test: whisper's trailing punctuation isn't perfectly deterministic across
    # two recordings of "the same" spoken phrase, which was silently missing the Phase 4
    # LLM cache (this text is the cache key) despite being the same command to a human ear.
    assert normalize_text("open a terminal.") == normalize_text("open a terminal")
    assert normalize_text("Switch to workspace two!") == "switch to workspace two"


def test_resolve_app_window_class_uses_explicit_override():
    from hypr_vocal_command.config import Config

    config = Config()
    # vscode's real Hyprland class ("code") differs from its registry key ("vscode") --
    # confirmed against a real running instance; must use the explicit override, not
    # the key-based fallback guess.
    assert config.resolve_app_window_class("vscode") == "code"


def test_resolve_app_window_class_falls_back_to_registry_key():
    from hypr_vocal_command.config import Config

    config = Config()
    # spotify has no explicit window_class override -- the fallback guess (its own
    # registry key) happens to be correct, confirmed against a real running instance.
    assert config.resolve_app_window_class("spotify") == "spotify"


def test_resolve_app_window_class_returns_none_for_unknown_app():
    from hypr_vocal_command.config import Config

    assert Config().resolve_app_window_class("some totally unknown app") is None


def test_load_config_with_no_files_uses_defaults(tmp_path):
    config = load_config(
        path=tmp_path / "config.toml", generated_path=tmp_path / "apps.generated.toml"
    )
    assert config.resolve_app("obsidian") is not None


def test_generated_apps_are_merged_in(tmp_path):
    entries = [
        AppEntry(
            key="firefox",
            name="Firefox",
            surface_forms=("firefox",),
            manager="native",
            identifier="firefox",
            package_name="firefox",
        )
    ]
    generated_path = tmp_path / "apps.generated.toml"
    write_generated_apps(entries, generated_path)

    config = load_config(path=tmp_path / "config.toml", generated_path=generated_path)

    assert config.resolve_app("firefox") is not None
    assert config.resolve_package("firefox") is not None
    # defaults from Phase 1 are still present alongside the generated entries
    assert config.resolve_app("obsidian") is not None


def test_config_toml_override_wins_over_generated(tmp_path):
    entries = [
        AppEntry(
            key="firefox",
            name="Firefox",
            surface_forms=("firefox",),
            manager="native",
            identifier="firefox",
            package_name="firefox",
        )
    ]
    generated_path = tmp_path / "apps.generated.toml"
    write_generated_apps(entries, generated_path)

    config_toml = tmp_path / "config.toml"
    config_toml.write_text(
        '[apps.firefox]\n'
        'surface_forms = ["firefox", "the browser"]\n'
        'manager = "native"\n'
        'identifier = "firefox-esr"\n'
    )

    config = load_config(path=config_toml, generated_path=generated_path)

    alias = config.resolve_app("the browser")
    assert alias is not None
    assert alias.identifier == "firefox-esr"


def test_generated_apps_with_dotted_key_round_trips(tmp_path):
    entries = [
        AppEntry(
            key="org.example.DottedApp",
            name="Dotted App",
            surface_forms=("dotted app",),
            manager="flatpak",
            identifier="org.example.DottedApp",
            package_name=None,
        )
    ]
    generated_path = tmp_path / "apps.generated.toml"
    write_generated_apps(entries, generated_path)

    config = load_config(
        path=tmp_path / "config.toml", generated_path=generated_path
    )

    alias = config.resolve_app("dotted app")
    assert alias is not None
    assert alias.identifier == "org.example.DottedApp"
