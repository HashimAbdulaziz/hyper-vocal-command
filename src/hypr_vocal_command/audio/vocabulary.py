"""Builds a whisper `initial_prompt` from the registry's known command vocabulary.

This is a standard ASR technique for closed-vocabulary command systems: telling the
decoder what phrasing to expect measurably helps it disambiguate short commands, which
are otherwise out-of-distribution for a model trained mostly on natural continuous
speech (podcasts, lectures, audiobooks) rather than isolated 1-4 word commands.

Deliberately uses `DEFAULT_APPS` (a handful of hand-curated core apps), never the full
`config.apps` catalog (111+ entries once `scan-apps` has run) -- whisper's context window
is small (448 tokens on the base model, shared between prompt and decoded output), so
cramming in every scanned app would blow that budget and dilute the effect rather than
help. "obsidian" specifically was added here after live testing showed it repeatedly
mistranscribed as "save"/"oxygen" with no app-name vocabulary primed at all.
"""

from ..config import DEFAULT_APPS, Config

_GENERIC_EXAMPLES = (
    "open a terminal",
    "open the file manager",
    "go to workspace two",
    "go to workspace 2",
    "go to the next workspace",
)


def build_command_vocabulary_prompt(config: Config) -> str:
    phrases: list[str] = list(_GENERIC_EXAMPLES)
    for action_alias in config.hyprland_actions.values():
        phrases.extend(action_alias.surface_forms)
    for app_alias in DEFAULT_APPS.values():
        phrases.extend(app_alias.surface_forms)

    return ". ".join(dict.fromkeys(phrases)) + "."
