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

The prompt is also filtered by language, for the same budget reason: once Egyptian
Arabic surface forms were registered alongside the English ones, emitting every form
regardless of language pushed this past 540 tokens -- already over the 448-token
ceiling before any speech is decoded. Priming an English utterance with Arabic text (or
the reverse) also actively biases the decoder toward the wrong script.
"""

from ..config import DEFAULT_APPS, Config

_GENERIC_EXAMPLES_EN = (
    "open a terminal",
    "open the file manager",
    "go to workspace two",
    "go to workspace 2",
    "go to the next workspace",
)

# Egyptian Arabic is heavily code-switched in practice -- users say "افتح ال terminal"
# and "شغل سبوتيفاي" interchangeably -- so the Arabic prompt deliberately keeps the core
# English app names too, rather than being pure Arabic.
_GENERIC_EXAMPLES_AR = (
    "افتح التيرمينال",
    "شغل سبوتيفاي",
    "افتح الواتس",
    "اقفل الواتس",
    "روح للورك سبيس اتنين",
    "كبر الشاشه",
    "عايز اسمع اغاني",
    "terminal",
    "spotify",
    "whatsapp",
    "obsidian",
    "vscode",
    "chrome",
)


def _is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def build_command_vocabulary_prompt(config: Config, language: str = "en") -> str:
    """Whisper `initial_prompt` for the given language, filtered so an English pass is
    never primed with Arabic text or vice versa."""
    want_arabic = language == "ar"
    generic = _GENERIC_EXAMPLES_AR if want_arabic else _GENERIC_EXAMPLES_EN

    phrases: list[str] = list(generic)
    for action_alias in config.hyprland_actions.values():
        phrases.extend(f for f in action_alias.surface_forms if _is_arabic(f) == want_arabic)
    for app_alias in DEFAULT_APPS.values():
        phrases.extend(f for f in app_alias.surface_forms if _is_arabic(f) == want_arabic)

    return ". ".join(dict.fromkeys(phrases)) + "."
