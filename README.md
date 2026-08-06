# hypr-vocal-command

A fully local, offline voice-command execution daemon for Hyprland on Fedora. Press a
hotkey, speak a command in English or Egyptian Arabic, and it is transcribed,
classified, and executed as a real system action. Everything runs on-device: speech
recognition and intent classification both happen locally, with no cloud service and no
network calls beyond the machine itself.

This project is built specifically around one real Hyprland + Fedora setup rather than
as a generic, portable tool. Keybinds, application aliases, and a handful of custom
scripts are all matched to this machine's actual configuration. See "About this setup"
below for the specifics, and treat anything hardcoded (paths, keybinds, scripts) as a
concrete example to adapt rather than a universal default.

## What it can do

Every voice command maps to exactly one of twelve fixed, structured actions below.
Anything that doesn't clearly match one of these is refused rather than guessed at.

| Say | What happens |
|---|---|
| "open a terminal" | Opens the terminal emulator |
| "show me my files" / "open the file manager" | Opens the file manager |
| "open obsidian" / "open spotify" / "open whatsapp" / "open vscode" | Launches a named application |
| "take a screenshot" / "screenshot to clipboard" / "start screen recording" | Runs a registered shortcut |
| "lock screen" / "start task" / "bluetooth" / "system monitor" | Runs a registered personal shortcut |
| "close spotify" / "kill vscode" | Closes that application's window, on any workspace, focused or not |
| "close this window" / "make this floating" | Window-manager action on the currently focused window |
| "fullscreen this tile" / "maximize this window" | Fullscreen or maximize the focused window (two distinct actions) |
| "ungroup this window" / "group this window" | Frees the focused window from its tab-group, or joins one |
| "close this tab" / "new tab" | Sends Chrome's own Ctrl+W / Ctrl+T to the **focused** browser window |
| "focus right" / "swap window left" | Moves keyboard focus, or swaps tiles, in a direction |
| "show scratchpad" / "hide scratchpad" | Toggles the special scratchpad workspace |
| "go to workspace 2" | Switches to a specific numbered workspace |
| "go to the next workspace" / "go back a workspace" | Switches workspace relative to the current one |
| "move this window to workspace 3" | Sends the focused window to another workspace |
| "turn the volume up" / "mute" / "mute my mic" | System audio and microphone control |
| "make the screen brighter" / "dim the screen" | Screen backlight control |
| "play music" / "resume music" | Plays or resumes Spotify, launching it first if it isn't running |
| "pause music" / "stop music" | Pauses Spotify |
| "next song" / "go back a song" | Skips forward or back a track |
| "music" | Toggles play/pause, or launches Spotify if it isn't running |
| "update vscode" | Recognized, blocked pending a confirmation flow not yet built |
| "update all my flatpak apps" | Recognized, blocked pending a confirmation flow not yet built |

## Talk to your desktop in Egyptian Arabic

Most voice assistants expect Modern Standard Arabic -- a language nobody actually speaks
at home. This one is built for **Egyptian street Arabic**: the dialect, the slang, the
filler words, the half-English sentences, and the complaint you tack on at the end.

Say it the way you'd say it to a friend:

| Say this | And it does this |
|---|---|
| **"يسطا هات التيرمينال"** | Opens the terminal |
| **"اقفل الواتس بقى وجع دماغ"** | Closes WhatsApp (yes, including the complaint) |
| **"شيل اوبسيديان من قدامي خلاص"** | Closes Obsidian |
| **"عايز اكود افتحلي الاديتور"** | Opens VS Code |
| **"يا صاحبي افتح المتصفح"** | Opens Chrome |
| **"سمعنا حاجة وروقلنا الكلام"** | Plays music |
| **"غيرها"** | Skips to the next track |
| **"علي الصوت"** / **"وطي الصوت"** | Volume up / down |
| **"نور الشاشة"** | Turns the brightness up |
| **"كبر الشاشة"** | Fullscreens the focused window |
| **"فك الجروب"** | Frees the window from its tab-group |
| **"اقفل التابة دي"** | Closes the current browser tab |
| **"روح للورك سبيس اتنين"** | Switches to workspace 2 |
| **"ابعت الويندو دي للورك سبيس تلاتة"** | Sends this window to workspace 3 |
| **"رجعني الوركز بيس اللي قبلها"** | Goes back to the previous workspace |

What makes that work:

- **Code-switching is normal, not an edge case.** "افتح ال terminal", "شغل سبوتيفاي",
  "افتح الـ code editor" -- mix Arabic and English freely in one sentence.
- **Filler is ignored.** يسطا، يا صاحبي، بقولك إيه، كده، بقى، يبني، لو سمحت. So is a
  trailing grumble: "اقفل الواتس بقى وجع دماغ" closes WhatsApp and nothing else.
- **Concept words work, not just brand names.** المتصفح and البراوزر open Chrome,
  الاديتور opens VS Code, النوتس opens Obsidian, المزيكا is Spotify.
- **Spelling doesn't have to be right.** أوبسيديان and اوبسيديان, الشاشة and الشاشه all
  fold to the same thing before matching.
- **Mis-hearings are expected and recovered.** Speech recognition spells Egyptian
  phonetically and inconsistently -- "اوبسيديان" has come back as اكسيديا, بسيدياني and
  ابسيد بع across three recordings of the same word, and "ورك سبيس" as وركز بيس, ورك بيس
  and كسبيس. Names are matched approximately, and the workspace word fuzzily, so all of
  those still land. When two applications are too close to call apart, it refuses instead
  of guessing -- النوتس (Obsidian) and الواتس (WhatsApp) differ by one letter.
- **The verb decides, not the noun.** الشاشة means three different things depending on
  what you do to it: كبر الشاشة is fullscreen, نور الشاشة is brightness, اقفل الشاشه دي
  closes the window.

### Why the dialect is the hard part

Egyptians pronounce ق as a glottal stop, so **"اقفل"** (close) comes out closer to
"أ'فل" -- and a Modern-Standard-Arabic-trained recognizer hears "فين" (where) instead.
That single mismatch used to invert commands: asked to *close* WhatsApp, the pipeline
*opened* it. Fixing it needed a different speech model, not a bigger one; see the
language-support notes below.

## How it works

1. A hotkey press (`SUPER+ALT+V`) runs a minimal, near-instant trigger that wakes an
   already-running background daemon over a Unix domain socket. The trigger itself does
   nothing but send one message and exit; it has no heavy dependencies.
2. The daemon starts recording from the microphone. A voice-activity-detection model
   (Silero VAD) watches the audio in real time and automatically stops the recording
   once you stop speaking, so there is no separate "stop" step.
3. The recorded audio is transcribed to text locally using whisper.cpp (English) or a
   dedicated wav2vec2 CTC model (Egyptian Arabic).
4. The transcript first meets a small deterministic classifier. Simple, unambiguous
   commands -- opening and closing named apps, workspaces, window actions, volume --
   are recognized here in well under a millisecond and dispatched with **no language
   model involved at all**. Anything it does not recognize with certainty falls through
   to step 5 untouched.
5. Remaining transcripts go to a small local language model (served by Ollama) with a
   grammar-constrained output format: the model can only return one of a fixed,
   versioned set of structured intents, never arbitrary text or a shell command.
6. The returned intent is validated against that same schema and, if the model's
   confidence is high enough, dispatched to a hardcoded handler for that intent alone.
   Handlers execute through `subprocess` argument lists, `hyprctl` IPC, or D-Bus/MPRIS
   calls -- never by asking the model to produce a command to run directly.
7. Desktop notifications report what was heard and what happened, both on success and
   on failure (low confidence, unknown app, nothing to do, and so on).

Low-confidence results are refused rather than guessed, and results are cached briefly
so repeating the same command doesn't re-run the full classification step.

One further check sits between classification and execution: if a command names an
application, that name has to be traceable to something actually said. A model asked to
interpret a badly-transcribed sentence will sometimes answer with a plausible, familiar
application that appears nowhere in the audio -- and because the resulting action is
perfectly valid, it looks like success. Any application name that cannot be matched back
to the transcript is refused instead of run.

## Why this architecture

- The model that hears your voice is never the thing that runs commands. It selects
  from a fixed, versioned schema (built once from a single intent registry, shared by
  the classifier and the executor), and a plain Python dispatch table does the actual
  work. A misheard or ambiguous command can, at worst, trigger the wrong pre-approved
  action -- it cannot construct or run an arbitrary command.
- Every intent has an explicit, allow-listed handler. Application names, package names,
  and window-manager actions are all resolved through a configuration file, never
  executed as raw model output.
- A confidence threshold gates execution. Below it, nothing runs.
- Anything that changes system state beyond the current session (package or system
  updates) is recognized as an intent but requires a confirmation step that has not
  been built yet, so those two intents are currently inert by design rather than
  reachable without a safeguard.

## Tools and components

- **Hyprland** -- the target compositor; all window-manager actions go through
  `hyprctl dispatch`, the same IPC mechanism Hyprland's own keybinds use.
- **whisper.cpp** (via `pywhispercpp`) -- local speech-to-text for English, running the
  `base` model.
- **wav2vec2 CTC** (exported to ONNX) -- local speech-to-text for Egyptian Arabic,
  chosen over whisper on measured dialect accuracy; see "Language support".
- **Silero VAD** (via ONNX Runtime, CPU-only) -- voice-activity detection for automatic
  end-of-speech detection, with no PyTorch/CUDA dependency.
- **Ollama**, serving `llama3.2` locally -- intent classification through a
  grammar-constrained structured-output request, so the model's response is guaranteed
  to parse against a fixed JSON schema.
- **Pydantic v2** -- one intent registry drives both the JSON schema handed to the
  model and the executor's own validation and dispatch, so the two can never drift
  apart.
- **systemd** (`--user` service) -- keeps the whisper model, VAD session, and LLM
  client warm across requests instead of reloading them on every command.
- **playerctl** -- MPRIS media control, used for play/pause/resume and track skipping
  against Spotify.
- **wpctl** (PipeWire) and **brightnessctl** -- system volume, microphone mute, and
  screen backlight, invoked exactly as this machine's own media keys do.
- Python 3.14, Typer (developer CLI), httpx, cachetools.

## Keybinds

| Keybind | Action |
|---|---|
| `SUPER+ALT+V` | Trigger the voice pipeline, English |
| `SUPER+ALT+B` | Trigger the voice pipeline, Egyptian Arabic |

`SUPER+V` and `SUPER+B` were already bound on this setup (`togglefloating` and a
Bluetooth menu, respectively), hence `ALT` added to both.

## Configuration layering

Application and package aliases are resolved from three layers, each overriding the
one before it:

1. Built-in defaults -- a small, hand-curated set of core applications and
   window-manager actions.
2. `apps.generated.toml` -- regenerated by scanning installed `.desktop` files
   (`hypr-vocal-command scan-apps --write`); safe to re-run at any time.
3. `config.toml` -- hand-edited overrides, always take priority over the generated
   file.

## About this setup

This project assumes:

- Fedora 43, Hyprland (managed through UWSM), a systemd `--user` session.
- An Intel i7-8850H (6 physical cores) and an NVIDIA Quadro P2000 (4GB VRAM); whisper
  is explicitly pinned to 6 threads to match the physical core count, and the LLM is
  chosen to fit entirely inside the available VRAM rather than spill onto the CPU.
- A specific screenshot/screen-recording setup (`grim`, `slurp`, `swappy`, `wl-copy`,
  and a personal `screen-record.sh` script) mirrored exactly from this machine's own
  Hyprland keybinds.
- A personal Taskwarrior time-tracking script (`task-toggle.sh`) bound to a specific
  spoken phrase.

Adapting this to a different machine means revisiting the application alias list, the
window-manager action list, the model choice, and the thread count -- none of it is
auto-detected.

## Performance

Measured on the hardware described above, with the daemon warm (model, VAD session,
and LLM client already loaded -- this is the normal running state, not a cold start).

| Stage | Typical time |
|---|---|
| Trailing silence before recording stops | 0.7 second |
| Speech-to-text, Egyptian Arabic (wav2vec2 CTC) | roughly 210 milliseconds |
| Speech-to-text, English (whisper.cpp, `base` model) | roughly 1.1-2.3 seconds |
| Intent classification, deterministic fast path | under 1 millisecond |
| Intent classification, local LLM (GPU-resident) | roughly 2.3 seconds on average |
| Action execution (`hyprctl` dispatch) | about 5 milliseconds |

Most everyday commands never reach the language model. Roughly four out of five of the
Arabic regression phrases, and two out of three of the English ones, are recognized by
the deterministic fast path instead -- which puts a common Arabic command at **well
under a second end to end**, dominated entirely by the pause that ends the recording.

Commands that do need the model land around 2.3 seconds for classification.

Three points worth being explicit about:

- Once the model is skipped for simple commands, the trailing-silence wait becomes the
  single largest remaining cost -- it was measured at 82% of total latency for a fast
  path command, which is why it is tunable via `silence_timeout_s`.
- The classification step is bound by the local GPU's raw generation throughput for the
  chosen model. Prompt length is not free, though: measurably longer prompts cost both
  latency and accuracy on a model this size, which is why the two languages no longer
  share one prompt.
- Repeating an identical command shortly after the first attempt is served from a
  short-lived cache rather than reclassified.

## Language support

English (`SUPER+ALT+V`) and Egyptian Arabic (`SUPER+ALT+B`) are both supported. Every
command in the table above works in either language, through the same intents, the same
handlers, and the same warm daemon.

Each language gets its own system prompt containing only its own examples, rather than
one shared prompt carrying both. Measured on this hardware, that alone cut a noticeable
slice off every classification, since generation cost scales with context length.

Speech recognition differs by language. English uses whisper.cpp; Egyptian Arabic uses
a dedicated wav2vec2 CTC model instead, chosen on measured evidence rather than
assumption. Whisper's multilingual models are trained largely on Modern Standard Arabic
and mishear Egyptian pronunciation -- most damagingly on "اقفل" (close), which Egyptians
realize with a glottal stop. In a live comparison on real speech, whisper misread it as
"فين" (where) and the pipeline then *opened* WhatsApp when asked to close it. The CTC
model read the same recordings correctly and never inverted an action.

It is also faster, not slower: CTC decodes in a single forward pass with no
autoregressive loop, so it runs in roughly 680ms against whisper base's 1300ms, despite
having more parameters. An Egyptian-tuned whisper `small` was evaluated too and rejected
at roughly 6.1 seconds per command. The model is exported to ONNX ahead of time and runs
through the same `onnxruntime` this project already uses for voice-activity detection,
so it adds no new runtime dependency; PyTorch is needed only to produce the export.

Both languages share one classifier model. A dedicated Arabic LLM fine-tune was
evaluated and rejected: it does not fit this machine's 4GB of VRAM, so it ran at roughly
15.8 seconds per command against 2.5 seconds for the shared model, while classifying the
difficult Arabic phrases no more accurately. That choice is a configuration value
(`model_ar`) and can be revisited on different hardware without code changes.

## Development

```
pip install -e '.[dev,audio]'
pytest
ruff check src/
mypy src/
```

`hypr-vocal-command check-golden` classifies a persisted set of real test phrases
(`tests/fixtures/golden_phrases_en.json`) against the live model and reports pass/fail
and latency for each -- useful after any change to the prompt or the intent schema,
since it is the one thing that can only be checked against a running model rather than
in the regular test suite.

`hypr-vocal-command review-log` reads the daemon's own telemetry
(`~/.local/state/hypr-vocal-command/events.jsonl`) and reports every real voice command
from a time window (the last 24 hours by default) alongside what the pipeline decided
and what actually happened. This exists because collecting every real-world mishearing
or typo by hand doesn't scale -- Egyptian Arabic alone produced dozens of distinct
garbled spellings for the same handful of words in one session -- so the intended
workflow is: let the daemon run for a day of normal use, then run this once to see
everything it heard and did in one pass, instead of reacting to each mistake as it
happens.

It deliberately lists every command, not just the ones that failed. Several real,
dangerous misfires were found this way -- opening the wrong app on a garbled name,
closing whichever window happened to be focused instead of the one actually named, and
a request to go back a workspace that closed the browser instead -- and every one of
them logged as a clean success. A report that only surfaced failures would have hidden
exactly the mistakes that mattered most. Reviewing one day of real use this way turned
up fifteen misclassifications and drove the transcript-grounding check described above.
Heuristic flags (`blocked`, `low-margin-pass`, `inconsistent`) exist only to draw the
eye to rows worth a second look; they never hide a row. Once a real misclassification
is confirmed, the fix is the same as always -- a `config.py` alias or a
`llm/prompts.py` example -- and the phrase should be added to the matching
golden-phrase fixture so `check-golden` catches it again automatically from then on.

## Project status

Built so far: the deterministic executor and safety gating, application discovery from
installed `.desktop` files, LLM-based intent classification with a response cache, the
deterministic fast path that skips the model entirely for everyday commands, the full
audio pipeline (capture, voice-activity detection, transcription in both languages),
the transcript-grounding check against invented application names, the warm background
daemon and its Unix-socket protocol, the real Hyprland keybind integration with a
systemd `--user` service, and the telemetry review command used to find real
misclassifications after a day of ordinary use.

Not yet built: a real confirmation flow for destructive actions (package/system
updates), broader hardening for long-term unattended use, web search, and free-text
file lookup.

## License

MIT
