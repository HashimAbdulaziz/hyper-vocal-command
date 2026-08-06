"""A local, deterministic classifier tried BEFORE the LLM, so that simple, unambiguous
commands ("open obsidian", "اقفل الواتس", "go to workspace 2") can be dispatched without
paying the ~2-2.5s Ollama generation cost at all -- the goal is for the common case to
feel instant, while genuinely open-ended or ambiguous input (and, in the future, freeform
tasks like a web search) still goes through the full LLM reasoning path unchanged.

This is deliberately narrow and conservative rather than a full reimplementation of the
LLM's own reasoning. It reuses the exact same alias-resolution machinery the LLM path
already relies on (`config.resolve_app`, `resolve_app_window_class`,
`resolve_hyprland_action`, including their fuzzy-matching safety margins) rather than
inventing a second, parallel notion of "what app is this". The only new logic here is a
small amount of keyword-based verb/object splitting -- and on ANY doubt (a verb that
doesn't clearly resolve, more than one action category present, a media-adjacent word,
too-short input), it returns None and the caller falls through to the LLM exactly as
before. Wrong-but-confident is the only real risk this file could introduce; the design
goal is to make that structurally impossible by only ever accepting an answer that the
same resolver the LLM path uses would also accept, and refusing (never guessing) on
anything else.

MEDIA_CONTROL is deliberately excluded entirely: the play/pause/toggle polarity rules
("resume" vs "pause", bare "music" vs an explicit verb) and the "اقفل المزيكا" pause-vs-
close ambiguity took several rounds of hard-won prompt tuning (see llm/prompts.py) and
are not worth re-deriving by hand here. UPDATE_PACKAGE/UPDATE_SYSTEM are excluded too --
both are unconditionally blocked pending a confirmation flow, so there is no latency to
save. Spotify is excluded from the OPEN_APP/CLOSE_APP fast path specifically, since its
own registered aliases include music-concept words ("المزيكا"/"الاغاني") that overlap
with MEDIA_CONTROL's vocabulary -- exactly the ambiguity that requires the LLM's judgment.

These keyword lists intentionally mirror llm/prompts.py's Arabic verb-pattern block and
English examples rather than importing them (that text is prose meant for the model to
read, not a clean data structure) -- update both together if a new verb/filler word is
added to either.
"""

import difflib

from .config import Config, _resolve_alias, normalize_text

# Registered apps excluded from the fast path entirely because their own aliases overlap
# with MEDIA_CONTROL's vocabulary (see module docstring) -- always deferred to the LLM.
_MEDIA_ADJACENT_APPS = frozenset({"spotify"})

_OPEN_VERBS = frozenset(
    {
        "open", "launch", "start", "run", "bring", "up",
        "افتح", "افتحلي", "هات", "هاتلي", "شغل", "شغلي", "طلعلي", "ابدأ", "ادخل",
        # Real CTC spellings of the same verb, captured from the event log.
        "مفتح", "يفتح", "نفتح", "فتح", "افتحلنا", "تفتحلي",
    }
)
_CLOSE_VERBS = frozenset(
    {
        "close", "kill", "quit", "exit",
        "اقفل", "اقفله", "شيل", "اطفي", "اخرج", "اطلع", "انهي",
    }
)
# Any of these anywhere in the phrase hands the whole thing to the LLM -- this is
# exactly the vocabulary MEDIA_CONTROL's hard-won play/pause/close-vs-pause rules cover.
_MEDIA_KEYWORDS = frozenset(
    {
        "music", "play", "pause", "resume", "stop", "song", "songs",
        "اغاني", "الاغاني", "اغنيه", "مزيكا", "المزيكا", "موسيقى", "الموسيقى",
        "سمعنا", "اسمع", "وقف", "صدعت",
    }
)
_TERMINAL_KEYWORDS = ("terminal", "console", "shell", "تيرمينال", "سطر الاوامر", "كونسول")
_FILE_MANAGER_KEYWORDS = ("file manager", "files", "ملفات")
_COMPOUND_MARKERS = (" and ", " then ", "وبعدين", "كمان")

# Words that carry no meaning for object extraction: dialect filler, pronouns,
# prepositions, politeness -- stripping them can only ever cause a miss (fall through to
# the LLM), never a wrong-but-confident match, since whatever remains still has to
# resolve through the same resolve_app()/resolve_app_window_class() the LLM path uses.
_FILLER_WORDS = frozenset(
    {
        "i", "want", "to", "please", "can", "you", "the", "a", "my", "me", "show",
        "يسطا", "يا", "صاحبي", "بقولك", "ايه", "كده", "بقى", "يبني", "سمحت", "ممكن",
        "عايز", "محتاج", "كنت", "من", "على", "لي", "لنا", "دي", "ده", "بتاع", "بتاعي",
        "قدامي", "خلاص",
    }
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    # Cardinal numbers. Keys are the POST-normalize_text() spelling -- ta marbuta (ة)
    # folds to ه and alef maqsura (ى) folds to ي before this dict is ever consulted, so
    # a key written with the "standard" spelling (e.g. "ثلاثة") would silently never
    # match. Verified each of these against normalize_text() directly, not assumed.
    "واحد": 1, "اتنين": 2, "اثنين": 2, "اتنان": 2,
    "تلاته": 3, "ثلاثه": 3,
    "اربعه": 4, "خمسه": 5, "سته": 6, "سبعه": 7, "تمانيه": 8, "تسعه": 9, "عشره": 10,
    # Ordinals -- "روح للورك سباس الاولى" (go to the first workspace) names a workspace
    # by ordinal, not cardinal, position. Same post-fold spelling rule applies.
    "الاولي": 1, "اول": 1,
    "الثانيه": 2, "التانيه": 2, "تاني": 2,
    "الثالثه": 3, "التالته": 3, "تالت": 3,
    "الرابعه": 4, "رابع": 4,
    "الخامسه": 5, "خامس": 5,
    "السادسه": 6, "سادس": 6,
    "السابعه": 7, "سابع": 7,
    "الثامنه": 8, "تامن": 8,
    "التاسعه": 9, "تاسع": 9,
    "العاشره": 10, "عاشر": 10,
}
_WORKSPACE_KEYWORDS = (
    "workspace", "screen", "سكرين", "شاشة رقم",
    # "سبيس"/"سباس"/"سبس" are all real transcriptions of "space" for the same word --
    # substring matching means "ورك سبيس"/"ورك سباس"/"ورك سبس" all match here too, with
    # or without a leading "لل"/"ل" ("لورك سباس", "للورك سباس").
    "ورك سبيس", "ورك سباس", "ورك سبس",
)
# Every spelling of "tile"/"window" seen in real transcripts. Used as a signal that a
# workspace command is about relocating THIS window rather than just navigating.
_TILE_WORDS = frozenset({
    "tile", "window", "الطايل", "التايل", "طايل", "تايل", "الويندو", "ويندو",
    "البلاطه", "البلطه", "الباطه", "لطيل", "الطيل", "النادج", "البادج", "البدج",
    "طيل", "الطي", "الطايله", "تيل",
})

# Exact keywords cannot keep up with how badly CTC mangles "ورك سبيس": the event log has
# "وركز بيس", "ورك بيس", "وركزبيس", "الوركز بيس", "لويركز بيز", "كسبيس" -- all the same
# spoken word. Matched fuzzily instead, against the spaces-removed canonical form, over
# 1-2 word windows (the word is sometimes split across two tokens, sometimes not).
_WORKSPACE_CANONICAL = "وركسبيس"
_WORKSPACE_FUZZY_CUTOFF = 0.72

# Egyptian navigation verbs: "take me (back) to ...". Without these, "رجعني الوركز بيس
# اللي قبلها" reached the LLM, which answered CLOSE_APP{chrome} and closed the browser.
_GO_BACK_VERBS = ("رجعني", "رجعنى", "ارجعني", "رجع")
_TAKE_ME_VERBS = ("واديني", "ودني", "وديني", "خدني")
_NEXT_KEYWORDS = ("next", "جاي", "التالي")
_PREVIOUS_KEYWORDS = ("previous", "back", "رجعت", "اللي فات")

# "Send this window to workspace N" vs. "go to workspace N": same number, completely
# different outcome, so the move verbs are matched explicitly rather than inferred.
_MOVE_WINDOW_KEYWORDS = ("move", "send", "ابعت", "ابعتها", "انقل", "نقل", "حط", "وديها", "ودي")

# System volume / mic / brightness. Each entry is (keywords, action); the first entry
# whose keywords ALL appear wins, so more specific rules (mic, brightness) are listed
# before the generic volume ones and cannot be shadowed by them.
_SYSTEM_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    # Microphone first -- "اكتم المايك" also contains the generic mute vocabulary.
    (("mic",), "mic_mute"),
    (("microphone",), "mic_mute"),
    (("المايك",), "mic_mute"),
    (("الميك",), "mic_mute"),
    # Brightness.
    (("brightness", "up"), "brightness_up"),
    (("brighter",), "brightness_up"),
    (("نور الشاشه",), "brightness_up"),
    (("زود النور",), "brightness_up"),
    (("زود الاضاءه",), "brightness_up"),
    (("زود السطوع",), "brightness_up"),
    (("brightness", "down"), "brightness_down"),
    (("dim",), "brightness_down"),
    (("قلل النور",), "brightness_down"),
    (("وطي النور",), "brightness_down"),
    (("قلل الاضاءه",), "brightness_down"),
    (("قلل السطوع",), "brightness_down"),
    # Mute (system output).
    (("mute",), "volume_mute"),
    (("اكتم",), "volume_mute"),
    (("اسكت",), "volume_mute"),
    (("سكت الصوت",), "volume_mute"),
    # Volume up / down.
    (("volume", "up"), "volume_up"),
    (("louder",), "volume_up"),
    (("علي الصوت",), "volume_up"),
    (("عل السوت",), "volume_up"),
    (("علي السوت",), "volume_up"),
    (("على الصوت",), "volume_up"),
    (("زود الصوت",), "volume_up"),
    (("ارفع الصوت",), "volume_up"),
    (("اعلي الصوت",), "volume_up"),
    (("volume", "down"), "volume_down"),
    (("quieter",), "volume_down"),
    (("وطي الصوت",), "volume_down"),
    (("قلل الصوت",), "volume_down"),
    (("نزل الصوت",), "volume_down"),
    (("خفض الصوت",), "volume_down"),
)

# Track skipping. Checked before the media-keyword bail-out, since these ARE media
# commands -- unlike play/pause, next/previous carry no close-vs-pause ambiguity, so
# they are safe to resolve deterministically.
_TRACK_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("next", "track"), "next"),
    (("next", "song"), "next"),
    (("skip",), "next"),
    (("اللي بعده",), "next"),
    (("اللي بعدها",), "next"),
    (("غير الاغنيه",), "next"),
    (("غيرها",), "next"),
    (("غيرلي",), "next"),
    (("الاغنيه اللي بعدها",), "next"),
    (("previous", "track"), "previous"),
    (("previous", "song"), "previous"),
    (("اللي فاتت",), "previous"),
    (("اللي فات",), "previous"),
    (("رجع الاغنيه",), "previous"),
    (("الاغنيه اللي فاتت",), "previous"),
)


def _looks_compound(text: str) -> bool:
    padded = f" {text} "
    return any(marker in padded for marker in _COMPOUND_MARKERS)


def _verb_polarity(text: str) -> str | None:
    words = set(text.split())
    is_open = not words.isdisjoint(_OPEN_VERBS)
    is_close = not words.isdisjoint(_CLOSE_VERBS)
    if is_open and is_close:
        return None  # both verb categories present -- ambiguous, defer
    if is_open:
        return "open"
    if is_close:
        return "close"
    return None


def _strip_filler(text: str) -> str:
    drop = _FILLER_WORDS | _OPEN_VERBS | _CLOSE_VERBS
    return " ".join(w for w in text.split() if w not in drop)


def _envelope(intent: str, args: dict) -> dict:
    return {"schema_version": 1, "intent": intent, "confidence": 1.0, "args": args}


def _first_rule_match(text: str, rules: tuple[tuple[tuple[str, ...], str], ...]) -> str | None:
    for keywords, action in rules:
        if all(kw in text for kw in keywords):
            return action
    return None


def _try_system_control(text: str) -> dict | None:
    action = _first_rule_match(text, _SYSTEM_RULES)
    return _envelope("SYSTEM_CONTROL", {"action": action}) if action else None


def _try_track_skip(text: str) -> dict | None:
    action = _first_rule_match(text, _TRACK_RULES)
    return _envelope("MEDIA_CONTROL", {"action": action}) if action else None


def _extract_workspace_number(text: str) -> int | None:
    for word in text.split():
        if word.isdigit() and 1 <= int(word) <= 99:
            return int(word)
        if word in _NUMBER_WORDS:
            return _NUMBER_WORDS[word]
    return None


def _is_tile_word(word: str) -> bool:
    """Tile/window word, tolerating the Arabic prefixes CTC leaves attached to it --
    "للتايل" is لل + تايل, and "الطايل"/"طايل" differ only by the article."""
    if word in _TILE_WORDS:
        return True
    return any(len(t) >= 4 and word.endswith(t) for t in _TILE_WORDS)


def _mentions_workspace(text: str) -> bool:
    if any(kw in text for kw in _WORKSPACE_KEYWORDS):
        return True
    words = text.split()
    for span in (1, 2):
        for start in range(len(words) - span + 1):
            window = "".join(words[start : start + span])
            ratio = difflib.SequenceMatcher(None, window, _WORKSPACE_CANONICAL).ratio()
            if ratio >= _WORKSPACE_FUZZY_CUTOFF:
                return True
    return False


def _try_move_to_workspace(text: str) -> dict | None:
    if not _mentions_workspace(text):
        return None
    words = text.split()
    # A tile/window word alongside a workspace + number means "send THIS one there",
    # even when the move verb itself was garbled beyond recognition ("ان للتايل دي
    # لويركز بيز خمسة" -- the "انقل" survived only as "ان").
    names_a_tile = any(_is_tile_word(w) for w in words)
    if not names_a_tile and not any(
        kw in words or kw in text for kw in _MOVE_WINDOW_KEYWORDS
    ):
        return None
    number = _extract_workspace_number(text)
    # No relative form: "send this somewhere" without naming a destination is not
    # something to guess at, since it relocates a real window.
    return _envelope("MOVE_TO_WORKSPACE", {"workspace": number}) if number else None


def _try_workspace_switch(text: str) -> dict | None:
    if not _mentions_workspace(text):
        return None
    words = text.split()
    if any(kw in words or kw in text for kw in _MOVE_WINDOW_KEYWORDS):
        return None  # "move this to workspace 2" is a MOVE, handled above -- not a switch
    if any(_is_tile_word(w) for w in words):
        return None  # naming a tile means moving it, not navigating

    # "رجعني ... اللي قبلها" -- go back to the previous workspace.
    if any(v in words for v in _GO_BACK_VERBS):
        number = _extract_workspace_number(text)
        return _envelope("WORKSPACE_SWITCH", {"workspace": number or "previous"})
    if _verb_polarity(text) is not None:
        # An open/close verb is ALSO present -- e.g. "open spotify on workspace four".
        # That's two actions in one sentence; the workspace number alone isn't enough
        # signal that this is really just a workspace switch. Defer to the LLM, which
        # already has a dedicated compound-command refusal rule for exactly this.
        return None

    number = _extract_workspace_number(text)
    if number is not None:
        return _envelope("WORKSPACE_SWITCH", {"workspace": number})

    # No explicit number given -- only "next"/"previous" is safe to infer; never guess
    # a number (the same rule the LLM prompt itself states).
    if any(kw in text for kw in _NEXT_KEYWORDS):
        return _envelope("WORKSPACE_SWITCH", {"workspace": "next"})
    if any(kw in text for kw in _PREVIOUS_KEYWORDS):
        return _envelope("WORKSPACE_SWITCH", {"workspace": "previous"})
    return None


def _try_fixed_object_intent(text: str) -> dict | None:
    polarity = _verb_polarity(text)
    if polarity is None:
        return None

    has_terminal = any(kw in text for kw in _TERMINAL_KEYWORDS)
    has_file_manager = any(kw in text for kw in _FILE_MANAGER_KEYWORDS)
    if has_terminal and has_file_manager:
        return None  # two distinct objects named -- not a clean single command

    if polarity == "open" and has_terminal:
        return _envelope("OPEN_TERMINAL", {})
    if polarity == "open" and has_file_manager:
        return _envelope("OPEN_FILE_MANAGER", {})
    if polarity == "close" and has_terminal:
        # "اقفل التيرمينال" / "close the terminal" -- a terminal IS a named app when
        # closing it (see llm/prompts.py's Arabic examples); there is no CLOSE_APP
        # equivalent of OPEN_FILE_MANAGER since no file-manager app is registered.
        return _envelope("CLOSE_APP", {"app_name": "terminal"})
    return None


def _try_hyprland_action(text: str, config: Config) -> dict | None:
    # Exact whole-phrase match only -- deliberately NOT the handler's own
    # substring-fallback resolver, which exists to tolerate the LLM's own paraphrasing
    # of an already-extracted action phrase, not a raw sentence with filler around it.
    # An exact match here means there was no room for an app name to be hiding in the
    # rest of the sentence, so this can never collide with CLOSE_APP.
    result = _resolve_alias(config.hyprland_actions, text)
    if result is None:
        return None
    # `text` itself (not the alias's canonical surface_forms[0]) -- it already matched
    # exactly, and passing what was actually said keeps telemetry/messages faithful to
    # the real transcript instead of collapsing every phrasing to one canonical string.
    return _envelope("HYPRLAND_ACTION", {"action": text})


def _resolve_app_key(candidate: str, config: Config) -> str | None:
    """The registry key of the single app named in `candidate`, or None.

    Tries the whole phrase first, then individual words and short windows, because CTC
    routinely leaves garbage around the app name ("لينا ترمنه اللي عمنا" -- terminal,
    buried). Accepts a per-word result ONLY when every window points at the same app: if
    two different applications match, the phrase is ambiguous and belongs to the LLM
    rather than to a coin flip.
    """
    entry = config._resolve_app_entry(candidate)
    if entry is not None:
        return entry[0]

    words = candidate.split()
    keys: set[str] = set()
    for span in (1, 2):
        for start in range(len(words) - span + 1):
            found = config._resolve_app_entry(" ".join(words[start : start + span]))
            if found is not None:
                keys.add(found[0])
    return keys.pop() if len(keys) == 1 else None


def _try_app_open_close(text: str, config: Config) -> dict | None:
    polarity = _verb_polarity(text)
    if polarity is None:
        return None

    candidate = _strip_filler(text)
    if not candidate:
        return None

    key = _resolve_app_key(candidate, config)
    if key is None:
        return None
    if key in _MEDIA_ADJACENT_APPS:
        return None  # always defer Spotify to the LLM -- see module docstring

    if polarity == "open":
        return _envelope("OPEN_APP", {"app_name": key})

    window_class = config.resolve_app_window_class(candidate)
    if window_class is None:
        return None
    return _envelope("CLOSE_APP", {"app_name": key})


def try_fastpath(transcript: str, config: Config) -> dict | None:
    """Returns a complete envelope dict (ready for executor.execute()) for a small set
    of unambiguous commands, or None to signal "defer to the LLM" -- the normal,
    expected result for anything this file doesn't confidently recognize."""
    text = normalize_text(transcript)
    if not text or _looks_compound(text):
        return None

    # System volume/mic/brightness and track skipping are resolved BEFORE the media
    # bail-out below. Both are unambiguous in a way play/pause is not: "next track" has
    # no close-vs-pause reading, and "mute" is about system audio, not the player. They
    # do, however, share vocabulary with the media keywords ("song", "skip"), so order
    # matters -- checking them after the bail-out would make them unreachable.
    for early in (_try_system_control, _try_track_skip):
        result = early(text)
        if result is not None:
            return result

    if any(kw in text for kw in _MEDIA_KEYWORDS):
        return None

    for attempt in (_try_move_to_workspace, _try_workspace_switch, _try_fixed_object_intent):
        result = attempt(text)
        if result is not None:
            return result

    result = _try_hyprland_action(text, config)
    if result is not None:
        return result

    return _try_app_open_close(text, config)
