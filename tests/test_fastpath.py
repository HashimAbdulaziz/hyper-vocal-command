from hypr_vocal_command.config import Config
from hypr_vocal_command.fastpath import try_fastpath


def config() -> Config:
    return Config()


def test_workspace_switch_by_digit():
    env = try_fastpath("go to workspace 2", config())
    assert env["intent"] == "WORKSPACE_SWITCH"
    assert env["args"] == {"workspace": 2}


def test_workspace_switch_by_number_word():
    env = try_fastpath("switch to workspace one", config())
    assert env["args"] == {"workspace": 1}


def test_workspace_switch_arabic_number_word():
    env = try_fastpath("روح للورك سبيس اتنين", config())
    assert env["args"] == {"workspace": 2}


def test_workspace_switch_next():
    env = try_fastpath("go to the next workspace", config())
    assert env["args"] == {"workspace": "next"}


def test_workspace_switch_previous():
    env = try_fastpath("go back a workspace", config())
    assert env["args"] == {"workspace": "previous"}


def test_workspace_keyword_with_no_number_or_relative_word_defers():
    # Never invent a number -- same rule the LLM prompt itself states.
    assert try_fastpath("workspace please", config()) is None


def test_workspace_switch_defers_when_an_open_verb_is_also_present():
    # "open spotify on workspace four" -- a real compound command that was previously
    # forced into UNRECOGNIZED by the LLM's own compound-command guard. The workspace
    # number alone is not enough signal that this is really just a workspace switch.
    assert try_fastpath("open spotify on workspace four", config()) is None


def test_open_terminal():
    env = try_fastpath("open a terminal", config())
    assert env["intent"] == "OPEN_TERMINAL"
    assert env["args"] == {}


def test_open_terminal_arabic():
    env = try_fastpath("افتح سطر الاوامر", config())
    assert env["intent"] == "OPEN_TERMINAL"


def test_close_terminal_is_close_app_not_open_terminal():
    env = try_fastpath("اقفل التيرمينال", config())
    assert env["intent"] == "CLOSE_APP"
    assert env["args"] == {"app_name": "terminal"}


def test_open_file_manager():
    env = try_fastpath("open the file manager", config())
    assert env["intent"] == "OPEN_FILE_MANAGER"


def test_hyprland_action_exact_match():
    env = try_fastpath("close this tile", config())
    assert env["intent"] == "HYPRLAND_ACTION"
    assert env["args"] == {"action": "close this tile"}


def test_hyprland_action_preserves_the_actual_matched_phrasing():
    # Not collapsed to one canonical string -- telemetry should reflect what was
    # actually said, even though every registered synonym dispatches identically.
    env = try_fastpath("kill this window", config())
    assert env["args"]["action"] == "kill this window"


def test_hyprland_action_arabic():
    env = try_fastpath("كبر الشاشة", config())
    assert env["intent"] == "HYPRLAND_ACTION"


def test_open_app_resolves_via_existing_alias_machinery():
    env = try_fastpath("open obsidian", config())
    assert env["intent"] == "OPEN_APP"
    assert env["args"] == {"app_name": "obsidian"}


def test_close_app_resolves_via_existing_alias_machinery():
    env = try_fastpath("close vscode", config())
    assert env["intent"] == "CLOSE_APP"
    assert env["args"] == {"app_name": "vscode"}


def test_open_app_still_uses_the_fuzzy_resolver_for_garbled_names():
    # Same safety-netted fuzzy matcher (cutoff + ambiguity margin) already used by the
    # LLM path -- a real garbled transcription of "اوبسيديان" from this project's own
    # collected data.
    env = try_fastpath("افتح لنا وبسيدين", config())
    assert env["intent"] == "OPEN_APP"
    assert env["args"] == {"app_name": "obsidian"}


def test_spotify_is_always_deferred_to_the_llm():
    # Spotify's own aliases include music-concept words that overlap with
    # MEDIA_CONTROL's vocabulary ("close the music" vs "pause the music") -- that
    # ambiguity needs the LLM's judgment, never a fast-path guess.
    assert try_fastpath("open spotify", config()) is None
    assert try_fastpath("close spotify", config()) is None


def test_media_keyword_anywhere_defers_to_the_llm():
    assert try_fastpath("play music", config()) is None
    assert try_fastpath("اقفل المزيكا", config()) is None


def test_generic_window_word_is_not_close_app():
    # Must resolve to the focused-window HYPRLAND_ACTION, never CLOSE_APP with a
    # pronoun/generic word as app_name -- the exact safety boundary this project found
    # a real bug in earlier (killactive firing for a named app).
    env = try_fastpath("close it", config())
    assert env["intent"] == "HYPRLAND_ACTION"


def test_compound_command_defers_to_the_llm():
    assert try_fastpath("open obsidian and close the terminal", config()) is None


def test_unresolvable_generic_phrase_defers():
    assert try_fastpath("افتح لي البرنامج بتاعي", config()) is None


def test_empty_transcript_defers():
    assert try_fastpath("", config()) is None


def test_workspace_ordinals_resolve_to_their_number():
    # "روح للورك سباس الاولى" names workspace 1 by ORDINAL ("the first"), not cardinal.
    for phrase in ("روح للورك سباس الاولى", "روح للورك سبس الاولى", "روح لورك سباس واحد"):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["args"] == {"workspace": 1}, phrase


def test_arabic_number_words_survive_orthographic_folding():
    # normalize_text() folds ة->ه before _NUMBER_WORDS is consulted, so keys written
    # with the unfolded spelling ("ثلاثة") would silently never match. Regression test
    # for exactly that: these were dead entries until the keys were corrected.
    assert try_fastpath("روح للورك سبيس ثلاثة", config())["args"] == {"workspace": 3}
    assert try_fastpath("روح للورك سبيس اربعة", config())["args"] == {"workspace": 4}


def test_tile_word_mishearings_close_the_focused_window():
    # "tile"/"window" comes back spelled many ways from speech-to-text. None of these
    # name a real app, so every one must be the focused-window action -- never CLOSE_APP.
    for phrase in (
        "اقفل الطايل دي",
        "اقفل البلاطة دي",
        "اقفل البلطة دي",
        "اقفل الباطة دي",
        "اقفل النادج دي",
        "اقفل البدج دي",
    ):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["intent"] == "HYPRLAND_ACTION", phrase


def test_ungroup_variants_resolve():
    # جروب/قروب/كروب are the same borrowed word "group" spelled three ways.
    for phrase in ("فك الجروب", "فك القروب", "فك الكروب", "فك الجروب بتاع التابة دي"):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["intent"] == "HYPRLAND_ACTION", phrase


def test_update_intents_are_never_fast_pathed():
    # No latency to save -- both are unconditionally blocked pending a confirmation
    # flow, so there's no reason to special-case them here at all.
    assert try_fastpath("update vscode", config()) is None
    assert try_fastpath("update all my flatpak apps", config()) is None


def test_volume_and_brightness_resolve_in_both_languages():
    for phrase, action in (
        ("علي الصوت", "volume_up"),
        ("زود الصوت", "volume_up"),
        ("turn the volume up", "volume_up"),
        ("وطي الصوت", "volume_down"),
        ("dim the screen", "brightness_down"),
        ("نور الشاشة", "brightness_up"),
        ("قلل النور", "brightness_down"),
    ):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["intent"] == "SYSTEM_CONTROL", phrase
        assert env["args"] == {"action": action}, phrase


def test_mic_mute_is_not_shadowed_by_generic_mute():
    # "اكتم المايك" contains the same mute vocabulary as "اكتم الصوت"; the mic rules are
    # ordered first so the specific device wins over the generic one.
    assert try_fastpath("اكتم الصوت", config())["args"] == {"action": "volume_mute"}
    assert try_fastpath("اكتم المايك", config())["args"] == {"action": "mic_mute"}
    assert try_fastpath("mute my mic", config())["args"] == {"action": "mic_mute"}


def test_brightness_does_not_collide_with_fullscreen():
    # "الشاشة" appears in fullscreen, brightness and close-window commands alike -- the
    # verb decides, so these must not resolve to the same thing.
    assert try_fastpath("نور الشاشة", config())["intent"] == "SYSTEM_CONTROL"
    assert try_fastpath("كبر الشاشة", config())["intent"] == "HYPRLAND_ACTION"
    assert try_fastpath("اقفل الشاشه دي", config())["intent"] == "HYPRLAND_ACTION"


def test_track_skip_resolves_despite_media_vocabulary():
    # Track skipping shares words with the play/pause vocabulary that is otherwise
    # deferred to the LLM; these are unambiguous, so they resolve here instead.
    for phrase, action in (
        ("next song", "next"),
        ("skip this", "next"),
        ("اللي بعده", "next"),
        ("غير الاغنية", "next"),
        ("previous track", "previous"),
        ("الاغنية اللي فاتت", "previous"),
    ):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["intent"] == "MEDIA_CONTROL", phrase
        assert env["args"] == {"action": action}, phrase


def test_play_pause_still_defers_to_the_llm():
    # The close-vs-pause ambiguity that needed the LLM is unchanged by adding skipping.
    assert try_fastpath("play music", config()) is None
    assert try_fastpath("اقفل المزيكا", config()) is None


def test_move_to_workspace_is_distinguished_from_switching():
    # Same number, very different outcome: one relocates a window, the other just
    # navigates. Confusing them would move a window the user never meant to touch.
    move = try_fastpath("ابعت الويندو دي للورك سبيس اتنين", config())
    assert move["intent"] == "MOVE_TO_WORKSPACE"
    assert move["args"] == {"workspace": 2}

    assert try_fastpath("move this window to workspace 2", config())["intent"] == "MOVE_TO_WORKSPACE"
    assert try_fastpath("روح للورك سبيس اتنين", config())["intent"] == "WORKSPACE_SWITCH"
    assert try_fastpath("go to workspace 2", config())["intent"] == "WORKSPACE_SWITCH"


def test_move_without_a_destination_number_defers():
    # Never guess where to send a real window.
    assert try_fastpath("ابعت الويندو دي للورك سبيس", config()) is None


def test_directional_focus_and_swap_resolve():
    for phrase in ("روح لليمين", "روح للشمال", "روح فوق", "روح تحت", "بدل مع اللي يمين"):
        env = try_fastpath(phrase, config())
        assert env is not None, phrase
        assert env["intent"] == "HYPRLAND_ACTION", phrase


def test_garbled_workspace_word_still_resolves():
    # CTC renders "ورك سبيس" a different way almost every time; these are all real.
    assert try_fastpath("واديني وركزبيس اثنين", config())["args"] == {"workspace": 2}
    assert try_fastpath("رجعني الوركز بيس اللي قبلها", config())["args"] == {
        "workspace": "previous"
    }


def test_go_back_verb_never_closes_an_app():
    # This exact phrase closed Chrome in real use.
    env = try_fastpath("رجعني الوركز بيس اللي قبلها", config())
    assert env["intent"] == "WORKSPACE_SWITCH"


def test_naming_a_tile_makes_it_a_move_not_a_switch():
    env = try_fastpath("ان لطيل دي للورك بيس خمسة", config())
    assert env["intent"] == "MOVE_TO_WORKSPACE"
    assert env["args"] == {"workspace": 5}


def test_exit_fullscreen_is_not_ungroup():
    # "فك" is also the ungroup verb, so "فك الفولسكرين" was dispatching moveoutofgroup.
    c = config()
    for phrase in ("فك الفولسكرين", "شيل الفلسكريم"):
        env = try_fastpath(phrase, c)
        assert env is not None, phrase
        assert c.resolve_hyprland_action(env["args"]["action"]).dispatcher == "fullscreen", phrase


def test_app_name_is_found_among_surrounding_garble():
    # "مفتح لينا ترمنة اللي عمنا" opened Spotify in real use; the app word is buried in
    # garble, so the whole-phrase resolve fails and per-word resolution has to catch it.
    env = try_fastpath("مفتح لينا ترمنة اللي عمنا", config())
    assert env is not None
    assert env["args"] == {"app_name": "terminal"}


def test_ambiguous_multi_app_phrase_still_defers():
    # Per-word resolution must not turn a phrase naming two apps into a coin flip.
    assert try_fastpath("افتح اوبسيديان والواتس", config()) is None
