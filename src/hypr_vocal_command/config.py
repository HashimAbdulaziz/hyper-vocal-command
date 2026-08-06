"""Loads and validates hypr-vocal-command configuration."""

import difflib
import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class AppAlias(BaseModel):
    surface_forms: list[str]
    manager: Literal["native", "flatpak"]
    identifier: str
    # Hyprland's actual window `class` for this app, used by CLOSE_APP to target the
    # right window regardless of focus/workspace. Often NOT the same as `identifier`
    # (e.g. vscode's identifier is "code" for launching, which happens to also be its
    # class -- but flatpak identifiers like "com.spotify.Client" never match the real
    # class at all, which is just "spotify"). Defaults to None; CLOSE_APP falls back to
    # guessing the alias's own registry key, which happens to be correct for many simple
    # apps (confirmed for spotify) but not all -- set this explicitly when the guess is
    # wrong for a given app, the same "hand-curate as gaps are found" pattern used
    # everywhere else in this file.
    window_class: str | None = None


class PackageAlias(BaseModel):
    surface_forms: list[str]
    manager: Literal["dnf", "flatpak"]
    identifier: str


class HyprlandActionAlias(BaseModel):
    surface_forms: list[str]
    dispatcher: str
    args: str = ""
    # When set, this action targets the window that currently has FOCUS, and only runs
    # if that window's Hyprland class matches this value -- the handler appends an
    # `address:0x...` selector for it. Needed for `sendshortcut` actions: a bare
    # `class:^(google-chrome)$` selector matches whichever Chrome window Hyprland
    # happens to return first, so with two Chrome windows open, "close this tab" could
    # close a tab in the window the user isn't even looking at. With `follow_mouse = 1`
    # (this setup), the focused window is the one under the pointer, which is what
    # "this tab" means to a person. Confirmed live that `address:` targeting is exact.
    target_active_class: str | None = None


DEFAULT_APPS: dict[str, AppAlias] = {
    "obsidian": AppAlias(
        surface_forms=[
            "obsidian",
            "notes",
            "vault",
            "obsidian vault",
            # Egyptian Arabic, including the concept words users reach for instead of the
            # product name ("the notes app", "the vault").
            "اوبسيديان",
            "النوتس",
            "نوتس",
            "الملاحظات",
            "برنامج النوتس",
            "الفولت",
            "فولت",
            # Real mis-hearings observed in live Egyptian-Arabic testing -- whisper drops
            # or mangles the opening alef and the ـيان ending. Deterministic backstop for
            # when the classifier passes the garbled word straight through. Kept at the
            # TAIL for the same reason as spotify's above: audio/vocabulary.py primes
            # whisper from the head of this list, and priming it with known-wrong
            # spellings would work against biasing it toward the correct one.
            "وبسيديان",
            "وبسيدين",
            "وبسينية",
            "ابسيديان",
            "اوبسيدين",
            "ابسيد",
            "بسيد",
            "ابسيدي",
            "بسيدي",
            "ابسدين",
            "وبسيدي",
            "ابسيدين",
        ],
        manager="flatpak",
        identifier="md.obsidian.Obsidian",
        # Real Hyprland window class is "md.Obsidian" (mixed case!), not the registry
        # key "obsidian" -- confirmed by launching a real instance and checking
        # `hyprctl clients -j`. Same class of mismatch as vscode's override below.
        window_class="md.Obsidian",
    ),
    "spotify": AppAlias(
        # "play music"/"run music"/etc. deliberately NOT registered here -- those are
        # ambiguous between "launch the app" and "resume paused playback", which only
        # MEDIA_CONTROL's handler can disambiguate at runtime (by checking whether
        # Spotify is already running). This alias stays for direct, explicit launches.
        surface_forms=[
            "spotify",
            # Egyptian Arabic. Bare "المزيكا"/"الاغاني" (music/songs) deliberately live in
            # MEDIA_CONTROL's prompt guidance instead of here, for the same open-vs-play
            # ambiguity reason as their English counterparts above.
            "سبوتيفاي",
            "اسبوتيفاي",
            "سبوتفاي",
            # "the music"/"the songs" as an APP name. These resolve here so that
            # "اقفل المزيكا" ("close the music") can actually close Spotify -- the user's
            # own phrasing list files those under closing Spotify, not pausing it. Bare
            # listening requests ("عايز اسمع اغاني") never carry an app_name at all and
            # still route to MEDIA_CONTROL, so this doesn't collide with playback.
            "music",
            "المزيكا",
            "مزيكا",
            "الاغاني",
            "اغاني",
            "الموسيقى",
            "موسيقى",
            # Known whisper mis-hearings of "spotify" -- vocabulary priming helps but
            # doesn't guarantee correct transcription; these are a deterministic backstop
            # so alias resolution still succeeds if the LLM passes the garbled text
            # through verbatim as app_name. Kept at the TAIL deliberately: audio/
            # vocabulary.py primes whisper with the head of this list, and priming the
            # decoder with known-WRONG spellings works directly against the goal of
            # biasing it toward the right one.
            "putify",
            "this putify",
        ],
        manager="flatpak",
        identifier="com.spotify.Client",
    ),
    "terminal": AppAlias(
        # Opening a terminal is its own intent (OPEN_TERMINAL) and does not go through
        # here -- this entry exists so CLOSE_APP can target a terminal *by name*
        # ("اقفل التيرمينال", "close the terminal"), which otherwise had no resolvable
        # app_name at all. Launching via this alias still works and is harmless.
        surface_forms=[
            "terminal",
            "kitty",
            "command line",
            "التيرمينال",
            "تيرمينال",
            "الترمينال",
            "شاشه الاوامر",
            "سطر الاوامر",
            # Real CTC mis-hearings of "تيرمينال" captured from the event log. Several
            # sit below the fuzzy cutoff on their own ("ترمنة" scores 0.62 against the
            # canonical spelling), so they have to be registered literally or the
            # transcript-grounding check in executor.py would refuse them.
            "الترم",
            "الترمنر",
            "الدرمنا",
            "ترمنه",
            "الترمنه",
            "ترمنا",
        ],
        manager="native",
        identifier="kitty",
        window_class="kitty",
    ),
    "chrome": AppAlias(
        # Not previously registered as a default at all -- only "google chrome" existed,
        # via scan-apps. Bare "chrome" and the Arabic browser concept words were both
        # unresolvable before this.
        surface_forms=[
            "chrome",
            "google chrome",
            "browser",
            "web browser",
            "كروم",
            "جوجل كروم",
            "المتصفح",
            "متصفح",
            "البراوزر",
            "براوزر",
        ],
        manager="native",
        identifier="/home/hashim/.local/bin/google-chrome",
        window_class="google-chrome",
    ),
    "vscode": AppAlias(
        surface_forms=[
            "vscode",
            "vs code",
            "visual studio code",
            "code",
            "editor",
            "code editor",
            # Egyptian Arabic, including transliterations and the concept words users
            # reach for ("the editor", "I want to code").
            "في اس كود",
            "فيجوال ستوديو كود",
            "فيجوال ستوديو",
            "فيجوال استديو",
            "فيجوال استوديو",
            "فيجوال ستديو",
            "الاديتور",
            "اديتور",
            "الايديتور",
            "ايديتور",
            "الكود ايديتور",
            "المحرر",
            "عايز اكود",
        ],
        manager="native",
        identifier="code",
        # Real Hyprland window class is "code", not the registry key "vscode" --
        # confirmed via `hyprctl clients -j` against a real running instance.
        window_class="code",
    ),
    "task_list": AppAlias(
        surface_forms=["task list", "taskwarrior", "task manager", "open tasks"],
        manager="native",
        identifier=(
            "kitty --class task-manager env HIDE_FETCH=1 zsh -c 'clear; task; exec zsh'"
        ),
    ),
    "timer_toggle": AppAlias(
        surface_forms=["start task", "start the last task", "toggle task", "toggle timer"],
        manager="native",
        identifier=str(Path.home() / ".scripts" / "task-toggle.sh"),
    ),
    "lock_screen": AppAlias(
        surface_forms=["lock screen", "lock my screen", "lock the screen"],
        manager="native",
        identifier="hyprlock",
    ),
    "whatsapp": AppAlias(
        # scanned as "whatsie" (the flatpak's own app name), but the user calls it
        # "whatsapp" by voice -- same identifier, an extra spoken name.
        surface_forms=[
            "whatsapp",
            "whatsie",
            "chatting",
            "chat",
            "i want to chat",
            "send message",
            "send a message",
            "i want to send a message",
            "i want to send message on whatsapp",
            # Egyptian Arabic. The classifier usually normalizes these to "whatsapp"
            # itself, but registering them keeps resolution working even when it passes
            # the Arabic through verbatim -- deterministic, and far cheaper than teaching
            # every variant through prompt examples.
            "الواتس",
            "واتس",
            "واتساب",
            "الواتساب",
            "الشات",
            "شات",
            "رسايل",
            "الرسايل",
        ],
        manager="flatpak",
        identifier="com.ktechpit.whatsie",
    ),
    "antigravity": AppAlias(
        surface_forms=["antigravity"], manager="native", identifier="/usr/share/antigravity/antigravity"
    ),
    "postman": AppAlias(
        surface_forms=["postman"], manager="flatpak", identifier="com.getpostman.Postman"
    ),
    "screenshot": AppAlias(
        # Mirrors the user's real SUPER+D keybind exactly (screenshot -> swappy editor).
        # The `sh -c '...'` wrapper is part of the identifier itself (same pattern as
        # task_list's `zsh -c '...'` below) -- shlex.split() keeps it as one token, so
        # `sh` (not our own subprocess call) is what interprets the pipe/substitution.
        # Never shell=True on our side; the shell invocation is an explicit, visible,
        # developer-authored argv element, not something built from LLM/user text.
        surface_forms=["take a screenshot", "take screenshot", "screenshot"],
        manager="native",
        identifier="sh -c 'grim -g \"$(slurp)\" - | swappy -f -'",
    ),
    "screenshot_clipboard": AppAlias(
        # Mirrors the user's SUPER+O keybind (screenshot -> clipboard, no editor).
        surface_forms=["screenshot to clipboard", "copy a screenshot", "screenshot clipboard"],
        manager="native",
        identifier="sh -c 'grim -g \"$(slurp)\" - | wl-copy'",
    ),
    "screen_recording": AppAlias(
        # Mirrors the user's SUPER+CTRL+SHIFT+R keybind exactly (their own toggle script).
        surface_forms=["start screen recording", "toggle screen recording", "record my screen", "screen recording"],
        manager="native",
        identifier=f"{Path.home() / '.scripts' / 'screen-record.sh'} toggle",
    ),
    "pause_recording": AppAlias(
        # Mirrors SUPER+CTRL+SHIFT+P -- distinct from screen_recording's start/stop toggle.
        surface_forms=["pause recording", "pause screen recording", "وقف التسجيل"],
        manager="native",
        identifier=f"{Path.home() / '.scripts' / 'screen-record.sh'} pause-toggle",
    ),
    # The remaining entries below all mirror one real keybind each from this user's own
    # hyprland.conf, following the exact same "register the real command as a launchable
    # shortcut" pattern as task_list/timer_toggle/lock_screen above -- found by scanning
    # that config directly, not guessed.
    "app_launcher": AppAlias(
        # Mirrors SUPER+R ($menu).
        surface_forms=["app launcher", "open launcher", "open the menu", "لانشر", "افتح اللانشر"],
        manager="native",
        identifier="sh -c 'pkill rofi || rofi -show drun -theme ~/.config/rofi/launcher/type-7/style-1.rasi'",
    ),
    "toggle_waybar": AppAlias(
        # Mirrors SUPER+SHIFT+B.
        surface_forms=["toggle waybar", "hide the bar", "show the bar", "اخفي البار", "وار البار"],
        manager="native",
        identifier="killall -SIGUSR1 waybar",
    ),
    # clipboard_history (SUPER+Y) deliberately NOT registered -- it pipes into `wofi`,
    # which isn't installed on this machine (confirmed: `which wofi` finds nothing), so
    # the real keybind is already broken independent of this pipeline. Worth fixing at
    # the system level (install wofi, or repoint the script at rofi) before wiring a
    # voice command to it.
    "bluetooth_menu": AppAlias(
        # Mirrors SUPER+B.
        surface_forms=["bluetooth", "bluetooth menu", "open bluetooth", "البلوتوث"],
        manager="native",
        identifier="sh -c 'pkill rofi || bash ~/.config/rofi/widgets/bluetooth.sh'",
    ),
    "notifications": AppAlias(
        # Mirrors SUPER+N.
        surface_forms=["notifications", "notification center", "الاشعارات"],
        manager="native",
        identifier="swaync-client -t -sw",
    ),
    "audio_mixer": AppAlias(
        # Mirrors SUPER+A.
        surface_forms=["audio mixer", "sound settings", "مكسر الصوت", "اعدادات الصوت"],
        manager="native",
        identifier="pavucontrol",
    ),
    "ranger_file_manager": AppAlias(
        # Mirrors SUPER+SHIFT+E -- a second, TUI file manager distinct from
        # OPEN_FILE_MANAGER's GUI nautilus.
        surface_forms=["ranger", "open ranger", "رينجر"],
        manager="native",
        identifier="kitty --class ranger -e ranger",
    ),
    "system_monitor": AppAlias(
        # Mirrors SUPER+ESCAPE.
        surface_forms=["system monitor", "btop", "open btop", "مراقب النظام"],
        manager="native",
        identifier="kitty --class btop -e btop",
    ),
    # invert_colors (SUPER+SHIFT+I) deliberately NOT registered -- its script,
    # ~/.config/hypr/toggle-invert.sh, doesn't exist on disk (confirmed), so that real
    # keybind is already broken independent of this pipeline. Fix the script/keybind
    # first, then this is a one-line addition.
    "solar_zen": AppAlias(
        # Mirrors SUPER+I.
        surface_forms=["solar zen mode", "solar zen", "وضع سولار"],
        manager="native",
        identifier=str(Path.home() / ".scripts" / "solar-zen-toggle.sh"),
    ),
    "qr_scanner": AppAlias(
        # Mirrors SUPER+SHIFT+Q.
        surface_forms=["qr scanner", "scan a qr code", "سكانر الكيو ار"],
        manager="native",
        identifier=str(Path.home() / ".scripts" / "qr-scanner.sh"),
    ),
    "ocr_scan": AppAlias(
        # Mirrors SUPER+SHIFT+X.
        surface_forms=["ocr scan", "extract text", "استخراج النص"],
        manager="native",
        identifier=str(Path.home() / ".scripts" / "ocr-scan.sh"),
    ),
    "toggle_layout": AppAlias(
        # Mirrors SUPER+SHIFT+R.
        surface_forms=["toggle layout", "switch layout", "غير الليأوت"],
        manager="native",
        identifier=str(Path.home() / ".config" / "hypr" / "toggle-layout.sh"),
    ),
}

DEFAULT_PACKAGES: dict[str, PackageAlias] = {
    "obsidian": PackageAlias(
        surface_forms=["obsidian"], manager="flatpak", identifier="md.obsidian.Obsidian"
    ),
    "vscode": PackageAlias(
        surface_forms=["vscode", "vs code", "visual studio code", "code"],
        manager="dnf",
        identifier="code",
    ),
}

# Real hyprctl dispatchers only (not `exec`-based launches, which live in DEFAULT_APPS
# above instead and reuse the OPEN_APP mechanism). Deliberately excludes `exit` (full
# session logout) -- too large a blast radius to leave un-gated; add it explicitly with
# requires_confirmation if you ever want it.
DEFAULT_HYPRLAND_ACTIONS: dict[str, HyprlandActionAlias] = {
    "close_window": HyprlandActionAlias(
        surface_forms=[
            "close this tile",
            "close this window",
            "close window",
            "close tile",
            "close this",
            "close it",
            "clean this tile",
            "clean this window",
            "shut this window",
            "shut this",
            "kill this window",
            "kill this",
            "get rid of this window",
            # Egyptian Arabic -- the focused window, with no app named.
            "اقفل الشاشه دي",
            "اقفل الويندو دي",
            "اقفل ده",
            "شيل ده من قدامي",
            "اقفل الويندو",
            "اقفل التايل",
            # "tile"/"window" said or mis-heard many different ways -- طايل/تايل are the
            # same word two ways, بلاطة/بلطة/باطة are progressive typos of "tile" (its
            # literal meaning, "slab"), نادج/بادج/بدج/دضج are CTC mis-hearings of
            # "window"/"widget" with no consistent spelling, and English "tile"/"window"/
            # "page" get code-switched in directly.
            "اقفل الطايل دي",
            "اقفل التايل دي",
            "اقفل ال tile",
            "اقفل ال tile دي",
            "اقفل ال window دي",
            "اقفل البلاطة دي",
            "اقفل البلطة دي",
            "اقفل الباطة دي",
            "اقفل النادج دي",
            "اقفلالبادج دي",
            "اقفل ال page دي",
            "اقفل البدج دي",
            "اقفل الدضج دب",
            "اقفل الطايل",
            "اقفل البلاطة",
            "اقفل البلطة",
            "اقفل الباطة",
            "اقفل النادج",
            "اقفل البادج",
            "اقفل البدج",
            # Further real CTC spellings captured from the event log.
            "اقفل الطي دي",
            "اقفل الطيل دي",
            "اقفل التيل دي",
            "اقفل الطايله دي",
            "اقفل الطي",
        ],
        dispatcher="killactive",
    ),
    # Restores the focused window from a tab-group ("Restore Grouping Keys" in this
    # user's dynamic_mode.conf: SUPER+G togglegroup / SUPER+SHIFT+G moveoutofgroup).
    # Confirmed live: always exits 0, "Window not in a group" in stdout (not an error)
    # when the focused window isn't grouped -- same safe no-op shape as closewindow.
    "toggle_group": HyprlandActionAlias(
        surface_forms=[
            "toggle group", "group this window", "group this",
            "جروب الطايل دي", "اعمل جروب", "حط في جروب", "ادخل في جروب",
            "قروب الطايل دي", "كروب الطايل دي", "دمج الطايل دي في جروب",
        ],
        dispatcher="togglegroup",
    ),
    "ungroup_window": HyprlandActionAlias(
        surface_forms=[
            "ungroup this window", "ungroup this",
            "فك الجروب",
            "فك الجروب بتاع التابة دي",
            "فك القروب",
            "فك الكروب",
            "فك الكروب بتاع التايل دي",
            "فك الجروب بتاع الطايل دي",
            "فك الجروب بتاع تتيل دي",
            "فك القروب بتاع التايل دي",
            "فك الكروب بتاع الطايل دي",
            "فك الجروب بتاع الويندو دي",
            "فك القروب بتاع الويندو دي",
            "فك الجروب بتاع البلاطة دي",
        ],
        dispatcher="moveoutofgroup",
    ),
    "pin_window": HyprlandActionAlias(
        surface_forms=["pin this window", "pin this", "ثبت النافذة دي", "ثبت الطايل دي"],
        dispatcher="pin",
        args="active",
    ),
    "toggle_pseudo": HyprlandActionAlias(
        surface_forms=["toggle pseudo", "pseudo tile this", "بسيدو تايل"],
        dispatcher="pseudo",
    ),
    # Chrome-specific, via Hyprland's own `sendshortcut` dispatcher -- sends the
    # browser's native Ctrl+T/Ctrl+W. Deliberately targets the FOCUSED window (see
    # target_active_class) rather than "any window of this class": a tab belongs to one
    # specific window, and with several Chrome windows open, a class selector would act
    # on an arbitrary one. "this tab" means the one in front of the user.
    "chrome_new_tab": HyprlandActionAlias(
        surface_forms=[
            "new tab", "open a new tab", "open new tab",
            "افتحلي تابة جديدة", "افتح تابة", "افتحلنا تابة اعمنا", "افتح تابة جديدة",
            "افتح tabe", "افتح تاب", "افتح تب", "افتح طب", "افتح تابة",
            "افتح صفحة جديدة", "افتحلي تاب جديد", "افتح تاب جديد",
            # Real CTC spellings of "تابة" from the event log -- these were resolving to
            # OPEN_APP chrome/vscode instead (opening a whole application rather than a
            # tab in the one already open).
            "افتح طبة جديدة", "افتح تيبة جديدة", "افتح طاب جديدة", "افتح تبة جديدة",
            "يفتح طبة جديد", "افتح تيبة جديد", "افتح طبة", "افتح تيبة", "افتح تبة",
        ],
        dispatcher="sendshortcut",
        args="CTRL,T",
        target_active_class="google-chrome",
    ),
    "chrome_close_tab": HyprlandActionAlias(
        surface_forms=[
            "close this tab", "close the tab", "close current tab",
            "اقل التابة دي", "اقفل ال tabe دي", "اقفل الصفحة دي", "اقفل التاب",
            "اقفل الطاب", "اقفل التابة دي", "عايز اقفل التابة دي", "عايز اقفل التبة دي",
            "اقفل التب", "اقفل الصفحه", "اقفل tab",
            # Real CTC spellings from the event log.
            "اقفل الطبة دي", "اقفل التبة دي", "اقفل الطبة", "اقفل التيبة دي",
            "اقفل الطاب دي", "عفي الالتابة دي",
        ],
        dispatcher="sendshortcut",
        args="CTRL,W",
        target_active_class="google-chrome",
    ),
    "toggle_floating": HyprlandActionAlias(
        surface_forms=["toggle floating", "make this floating", "float this window"],
        dispatcher="togglefloating",
    ),
    # Two distinct dispatches, matching this user's own SUPER+F / SUPER+SHIFT+F binds --
    # NOT synonyms. args="1" (maximize) keeps gaps/bar/curves, so on a workspace where the
    # window is already the sole tile it produces literally zero visible size/position
    # change (confirmed empirically: hyprctl clients showed identical [12,70]/[1896,998]
    # geometry before and after). args="0" (true fullscreen) goes edge-to-edge at full
    # monitor resolution, killing gaps/bar -- the dramatic, unambiguous effect "fullscreen"
    # colloquially implies. Previously conflated into one alias defaulting to args="1",
    # which is why "fullscreen this tile" looked like a no-op to the user despite the
    # dispatch reporting success.
    "maximize_window": HyprlandActionAlias(
        surface_forms=[
            "maximize this",
            "maximize window",
            "maximize this window",
            "ماكسيمايز",
            "كبر الويندو",
        ],
        dispatcher="fullscreen",
        args="1",
    ),
    "fullscreen_window": HyprlandActionAlias(
        surface_forms=[
            "fullscreen this",
            "fullscreen this tile",
            "fullscreen this window",
            "full screen this",
            "make this fullscreen",
            "go fullscreen",
            "true fullscreen",
            "toggle fullscreen",
            "toggle the fullscreen",
            "toggle fullscreen of this tile",
            "toggle fullscreen for this window",
            # Egyptian Arabic
            "فول سكرين",
            "فولسكرين",
            "كبر الشاشه",
            "كبر الشاشه دي",
            "افرد الشاشه",
            "الشاشه كامله",
            "خلي الشاشه كامله",
            "شاشه كامله",
            "وسع الشاشه",
            "كبر البرنامج",
            # Exiting fullscreen is the SAME dispatch -- Hyprland's `fullscreen` is a
            # toggle -- so these belong here rather than needing their own action.
            # Registered explicitly because "فك"/"شيل" are also the ungroup/close verbs:
            # "فك الفولسكرين" was resolving to moveoutofgroup, and "شيل الفلسكريم" to
            # CLOSE_APP with a nonsense app name. Both from the real event log.
            "فك الفولسكرين",
            "فك الفلسكرين",
            "شيل الفولسكرين",
            "شيل الفلسكريم",
            "الغي الفولسكرين",
            "اعمل فولسكرين",
            "فولسكرين",
            "الفولسكرين",
            "الفلسكريم",
        ],
        dispatcher="fullscreen",
        args="0",
    ),
    "toggle_split": HyprlandActionAlias(
        surface_forms=["toggle split"],
        dispatcher="togglesplit",
    ),
    # Directional focus / window swapping, mirroring SUPER+arrows and SUPER+SHIFT+arrows.
    # Egyptian speakers give directions as يمين/شمال (right/left) far more than the MSA
    # يسار, and "روح" (go) is the everyday verb for moving focus.
    "focus_left": HyprlandActionAlias(
        surface_forms=[
            "focus left", "go left", "move focus left",
            "روح للشمال", "روح شمال", "الشمال", "اتحرك شمال",
        ],
        dispatcher="movefocus",
        args="l",
    ),
    "focus_right": HyprlandActionAlias(
        surface_forms=[
            "focus right", "go right", "move focus right",
            "روح لليمين", "روح يمين", "اليمين", "اتحرك يمين",
        ],
        dispatcher="movefocus",
        args="r",
    ),
    "focus_up": HyprlandActionAlias(
        surface_forms=["focus up", "go up", "move focus up", "روح فوق", "اتحرك فوق"],
        dispatcher="movefocus",
        args="u",
    ),
    "focus_down": HyprlandActionAlias(
        surface_forms=["focus down", "go down", "move focus down", "روح تحت", "اتحرك تحت"],
        dispatcher="movefocus",
        args="d",
    ),
    "swap_left": HyprlandActionAlias(
        surface_forms=[
            "swap left", "swap window left", "move this window left",
            "بدل مع اللي شمال", "حرك الويندو شمال", "نقل الويندو شمال",
        ],
        dispatcher="swapwindow",
        args="l",
    ),
    "swap_right": HyprlandActionAlias(
        surface_forms=[
            "swap right", "swap window right", "move this window right",
            "بدل مع اللي يمين", "حرك الويندو يمين", "نقل الويندو يمين",
        ],
        dispatcher="swapwindow",
        args="r",
    ),
    "swap_up": HyprlandActionAlias(
        surface_forms=["swap up", "swap window up", "حرك الويندو فوق"],
        dispatcher="swapwindow",
        args="u",
    ),
    "swap_down": HyprlandActionAlias(
        surface_forms=["swap down", "swap window down", "حرك الويندو تحت"],
        dispatcher="swapwindow",
        args="d",
    ),
    "toggle_scratchpad": HyprlandActionAlias(
        surface_forms=[
            "toggle scratchpad",
            "show scratchpad",
            "hide scratchpad",
            "open scratchpad",
            "close scratchpad",
        ],
        dispatcher="togglespecialworkspace",
        args="scratchpad",
    ),
}


# Arabic orthographic variants that carry no pronunciation difference for our purposes
# but are distinct codepoints, so they'd silently fail exact alias matching. Real example
# from this project's own collected phrasings: users write both "أوبسيديان" and
# "اوبسيديان" for Obsidian, and both "المزيكة"/"المزيكه" for music.
_ARABIC_CHAR_FOLDING = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",  # hamzated alef forms -> plain alef
        "ى": "ي",  # alef maqsura -> ya
        "ة": "ه",  # ta marbuta -> ha
        "ؤ": "و",
        "ئ": "ي",
        "ـ": "",  # tatweel (kashida), a purely decorative stretching character
    }
)


def normalize_text(text: str) -> str:
    # Strips punctuation too, not just case/whitespace -- whisper's own punctuation choice
    # (a trailing period, in particular) isn't perfectly deterministic across two separate
    # recordings of "the same" spoken phrase, and this text feeds the Phase 4 LLM response
    # cache's key (llm/cache.py) as well as alias surface-form matching here. Without this,
    # "open a terminal." vs "open a terminal" would silently miss the cache despite being
    # the same command to a human ear. Arabic punctuation (؟ ، ؛) is covered by the same
    # class, and Arabic diacritics (tashkeel) are dropped by it as well.
    text = re.sub(r"[^\w\s]", "", text.lower())
    text = text.translate(_ARABIC_CHAR_FOLDING)
    return " ".join(text.split())


def _resolve_alias(
    aliases: dict[str, AppAlias] | dict[str, PackageAlias] | dict[str, HyprlandActionAlias],
    spoken_name: str,
) -> tuple[str, AppAlias | PackageAlias | HyprlandActionAlias] | None:
    target = normalize_text(spoken_name)
    for key, alias in aliases.items():
        if target in (normalize_text(form) for form in alias.surface_forms):
            return key, alias
    return None


# Tuned against real garbled transcripts, not picked by feel. At 0.75 the observed
# mis-hearings of "اوبسيديان" ("اكسيديا" 0.80, "بسيدياني" 0.88, "ابسيد بع" 0.77) and of
# other apps ("الواتسب" 0.93, "كرومم" 0.89) all resolve, while a mis-hearing that would
# have resolved to the WRONG app ("فيلاكسي" -> vscode, 0.60) stays below the line.
_FUZZY_CUTOFF = 0.75
# ...but a cutoff alone is not enough: "النوتس" (obsidian) and "الواتس" (whatsapp) are
# 0.83 similar to each other, differing by one letter, so a garbled input can sit close
# to two different apps at once. Acting on that would close or launch the wrong
# application. When the top two candidates are different apps within this margin, the
# input is treated as ambiguous and refused instead.
_FUZZY_AMBIGUITY_MARGIN = 0.08
# Very short inputs are too easy to match against everything, so they are never fuzzed.
_FUZZY_MIN_LENGTH = 4


def _fuzzy_resolve_app(
    aliases: dict[str, AppAlias], spoken_name: str
) -> tuple[str, AppAlias] | None:
    """Best-effort match for app names that speech-to-text garbled.

    Only used after exact matching fails. CTC recognizers have no internal language
    model, so they spell phonetically and inconsistently -- "اوبسيديان" came back as
    "اكسيديا", "بسيدياني" and "ابسيد بع" across three separate utterances of the same
    word. Enumerating those variants as aliases cannot keep up; matching approximately
    can, provided it refuses when the answer is not clear-cut.
    """
    target = normalize_text(spoken_name)
    if len(target) < _FUZZY_MIN_LENGTH:
        return None

    best_per_key: dict[str, float] = {}
    for key, alias in aliases.items():
        best_per_key[key] = max(
            (
                difflib.SequenceMatcher(None, target, normalize_text(form)).ratio()
                for form in alias.surface_forms
            ),
            default=0.0,
        )

    ranked = sorted(best_per_key.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < _FUZZY_CUTOFF:
        return None
    if len(ranked) > 1 and (ranked[0][1] - ranked[1][1]) < _FUZZY_AMBIGUITY_MARGIN:
        return None  # too close to call between two different apps -- refuse

    key = ranked[0][0]
    return key, aliases[key]


def _resolve_hyprland_action(
    aliases: dict[str, HyprlandActionAlias], spoken_name: str
) -> HyprlandActionAlias | None:
    # Free-text "name a WM action" is more open-ended than naming a specific app/package --
    # empirically the LLM sometimes emits its own slug (e.g. "toggle_floating") or a bare
    # word (e.g. "close", "fullscreen") instead of one of our exact surface forms. This
    # small, curated action space (~5 entries) makes substring-containment fallback low-risk,
    # unlike the open-ended app/package alias space where that would invite ambiguity.
    target = normalize_text(spoken_name.replace("_", " "))

    for alias in aliases.values():
        if target in (normalize_text(form) for form in alias.surface_forms):
            return alias

    # Whole-WORD containment, not raw substring. A raw substring check silently matched
    # opposite actions: "group this" is a substring of "ungroup this tab", so an ungroup
    # request resolved to togglegroup and grouped the window instead of freeing it.
    # Comparing word sequences makes "group" and "ungroup" distinct, as they are to a
    # person. Found by the golden fixture, not by reading the code.
    target_words = target.split()
    if not target_words:
        return None
    for alias in aliases.values():
        for form in alias.surface_forms:
            form_words = normalize_text(form).split()
            if not form_words:
                continue
            if _contains_words(target_words, form_words) or _contains_words(
                form_words, target_words
            ):
                return alias
    return None


def _contains_words(haystack: list[str], needle: list[str]) -> bool:
    """True when `needle` appears in `haystack` as a contiguous run of whole words."""
    if len(needle) > len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


class Config(BaseModel):
    confidence_threshold: float = 0.6
    terminal_cmd: list[str] = Field(default_factory=lambda: ["kitty"])
    file_manager_cmd: list[str] = Field(default_factory=lambda: ["nautilus"])
    allowed_roots: list[Path] = Field(default_factory=lambda: [Path.home()])
    model_en: str = "llama3.2:latest"
    # Egyptian Arabic deliberately uses the SAME model as English, not the dedicated
    # `arazn-arabic` fine-tune that was originally planned for it. Measured on this
    # hardware: arazn-arabic is 5.6GB, does not fit the P2000's 4GB VRAM, and therefore
    # runs at a 45%/55% CPU/GPU split averaging ~15.8s per classification (vs ~2.5s for
    # llama3.2, which stays fully GPU-resident) -- and on a head-to-head over the exact
    # Arabic phrases llama3.2 got wrong, it fixed only one of five while regressing
    # others. It is a conversational Arabic fine-tune, not an instruction-following
    # structured-output model, which is what this task actually needs. Loading it would
    # also evict llama3.2 from VRAM, causing a model reload on every language switch.
    # Kept as a separate setting so it can be pointed elsewhere without code changes.
    model_ar: str = "llama3.2:latest"
    ollama_base_url: str = "http://localhost:11434"
    llm_timeout_s: float = 60.0
    # How long a pause must last before recording stops. Exposed here (rather than only
    # as an audio/vad.py default) because it is the single largest remaining cost in the
    # pipeline -- see that file's comment -- and the right value is a matter of personal
    # speaking rhythm, so it should be tunable from config.toml without a code change.
    silence_timeout_s: float = 0.7
    allowed_transcription_languages: list[str] = Field(default_factory=lambda: ["en", "ar"])
    apps: dict[str, AppAlias] = Field(default_factory=lambda: dict(DEFAULT_APPS))
    packages: dict[str, PackageAlias] = Field(default_factory=lambda: dict(DEFAULT_PACKAGES))
    hyprland_actions: dict[str, HyprlandActionAlias] = Field(
        default_factory=lambda: dict(DEFAULT_HYPRLAND_ACTIONS)
    )

    def _resolve_app_entry(self, spoken_name: str) -> tuple[str, AppAlias] | None:
        result = _resolve_alias(self.apps, spoken_name)
        if result is not None and isinstance(result[1], AppAlias):
            return result[0], result[1]
        return _fuzzy_resolve_app(self.apps, spoken_name)

    def resolve_app(self, spoken_name: str) -> AppAlias | None:
        entry = self._resolve_app_entry(spoken_name)
        return entry[1] if entry else None

    def resolve_app_window_class(self, spoken_name: str) -> str | None:
        """Best-effort Hyprland window `class` for a spoken app name -- the alias's
        explicit `window_class` if set, else the alias's own registry key as a fallback
        guess (correct for many simple apps, e.g. "spotify", but not guaranteed)."""
        entry = self._resolve_app_entry(spoken_name)
        if entry is None:
            return None
        key, alias = entry
        return alias.window_class or key

    def resolve_package(self, spoken_name: str) -> PackageAlias | None:
        result = _resolve_alias(self.packages, spoken_name)
        if result is None:
            return None
        alias = result[1]
        return alias if isinstance(alias, PackageAlias) else None

    def resolve_hyprland_action(self, spoken_name: str) -> HyprlandActionAlias | None:
        return _resolve_hyprland_action(self.hyprland_actions, spoken_name)

    def model_for(self, language: str) -> str:
        """The classifier model to use for a supported language code."""
        try:
            return {"en": self.model_en, "ar": self.model_ar}[language]
        except KeyError:
            raise ValueError(f"unsupported language: {language!r}") from None


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def config_path() -> Path:
    return _xdg_config_home() / "hypr-vocal-command" / "config.toml"


def generated_apps_path() -> Path:
    return config_path().parent / "apps.generated.toml"


def _load_alias_layer(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Path | None = None, generated_path: Path | None = None) -> Config:
    """Layers config in increasing priority: built-in defaults < apps.generated.toml
    (regenerated by `scan-apps`) < config.toml (hand-edited overrides)."""
    path = path or config_path()
    generated_path = generated_path or generated_apps_path()

    apps: dict[str, AppAlias] = dict(DEFAULT_APPS)
    packages: dict[str, PackageAlias] = dict(DEFAULT_PACKAGES)
    hyprland_actions: dict[str, HyprlandActionAlias] = dict(DEFAULT_HYPRLAND_ACTIONS)

    generated = _load_alias_layer(generated_path)
    apps.update({k: AppAlias(**v) for k, v in generated.get("apps", {}).items()})
    packages.update({k: PackageAlias(**v) for k, v in generated.get("packages", {}).items()})

    overrides = _load_alias_layer(path)
    apps.update({k: AppAlias(**v) for k, v in overrides.get("apps", {}).items()})
    packages.update({k: PackageAlias(**v) for k, v in overrides.get("packages", {}).items()})
    hyprland_actions.update(
        {k: HyprlandActionAlias(**v) for k, v in overrides.get("hyprland_actions", {}).items()}
    )

    scalar_overrides = {
        k: v for k, v in overrides.items() if k not in ("apps", "packages", "hyprland_actions")
    }

    return Config(
        apps=apps, packages=packages, hyprland_actions=hyprland_actions, **scalar_overrides
    )
