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

Only the first few surface forms per alias per script are emitted, for a reason beyond
budget: priming and resolution want *opposite* things from the alias list. Resolution
needs every mis-hearing enumerated ("وبسيدين", "ابسيد", "putify") so garbled output
still matches something; priming needs the decoder biased toward the CORRECT spelling,
and feeding it a pile of known-wrong spellings works directly against that. Surface
forms are ordered canonical-first throughout config.py, so taking the head of each list
keeps the real names and drops the mis-hearing backstops -- which is what this prompt
should contain anyway.
"""

from ..config import DEFAULT_APPS, Config

# Per-alias, per-script cap. At 2 the English prompt is ~293 and the Arabic ~186
# approximate tokens, both well inside whisper's 448-token context (shared with decoded
# output), with room for more aliases before this needs revisiting. 2 rather than 3
# because the mis-hearing backstops sit close behind the canonical name on the aliases
# that have them -- at 3, "putify" was still reaching the prompt.
_MAX_FORMS_PER_ALIAS = 2

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
    # "اقفل" is repeated across several phrasings on purpose. Egyptian Arabic realizes
    # ق as a glottal stop, so "اقفل" is spoken closer to "أ'فل" -- whisper, trained
    # mostly on Modern Standard Arabic where ق is a hard /q/, mis-hears it as "اي اففي"
    # or "افقي". Priming the written form repeatedly biases the decoder back toward it.
    "اقفل الواتس",
    "اقفل اوبسيديان",
    "اقفل التيرمينال",
    "اقفل الشاشه دي",
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
        matching = [f for f in action_alias.surface_forms if _is_arabic(f) == want_arabic]
        phrases.extend(matching[:_MAX_FORMS_PER_ALIAS])
    for app_alias in DEFAULT_APPS.values():
        matching = [f for f in app_alias.surface_forms if _is_arabic(f) == want_arabic]
        phrases.extend(matching[:_MAX_FORMS_PER_ALIAS])

    return ". ".join(dict.fromkeys(phrases)) + "."
