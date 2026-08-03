# hypr-vocal-command

A fully local, offline voice-command execution daemon for Hyprland on Fedora. Press a
hotkey, speak a command in plain English, and it is transcribed, classified, and
executed as a real system action. Everything runs on-device: speech recognition and
intent classification both happen locally, with no cloud service and no network calls
beyond the machine itself.

This project is built specifically around one real Hyprland + Fedora setup rather than
as a generic, portable tool. Keybinds, application aliases, and a handful of custom
scripts are all matched to this machine's actual configuration. See "About this setup"
below for the specifics, and treat anything hardcoded (paths, keybinds, scripts) as a
concrete example to adapt rather than a universal default.

## What it can do

Every voice command maps to exactly one of nine fixed, structured actions below.
Anything that doesn't clearly match one of these is refused rather than guessed at.

| Say | What happens |
|---|---|
| "open a terminal" | Opens the terminal emulator |
| "show me my files" / "open the file manager" | Opens the file manager |
| "open obsidian" / "open spotify" / "open whatsapp" / "open vscode" | Launches a named application |
| "take a screenshot" / "screenshot to clipboard" / "start screen recording" | Runs a registered shortcut |
| "lock screen" / "start task" | Runs a registered personal shortcut |
| "close spotify" / "kill vscode" | Closes that application's window, on any workspace, focused or not |
| "close this window" / "make this floating" | Window-manager action on the currently focused window |
| "fullscreen this tile" / "maximize this window" | Fullscreen or maximize the focused window (two distinct actions) |
| "show scratchpad" / "hide scratchpad" | Toggles the special scratchpad workspace |
| "go to workspace 2" | Switches to a specific numbered workspace |
| "go to the next workspace" / "go back a workspace" | Switches workspace relative to the current one |
| "play music" / "resume music" | Plays or resumes Spotify, launching it first if it isn't running |
| "pause music" / "stop music" | Pauses Spotify |
| "music" | Toggles play/pause, or launches Spotify if it isn't running |
| "update vscode" | Recognized, blocked pending a confirmation flow not yet built |
| "update all my flatpak apps" | Recognized, blocked pending a confirmation flow not yet built |

## How it works

1. A hotkey press (`SUPER+ALT+V`) runs a minimal, near-instant trigger that wakes an
   already-running background daemon over a Unix domain socket. The trigger itself does
   nothing but send one message and exit; it has no heavy dependencies.
2. The daemon starts recording from the microphone. A voice-activity-detection model
   (Silero VAD) watches the audio in real time and automatically stops the recording
   once you stop speaking, so there is no separate "stop" step.
3. The recorded audio is transcribed to text locally using whisper.cpp.
4. The transcript is sent to a small local language model (served by Ollama) with a
   grammar-constrained output format: the model can only return one of a fixed,
   versioned set of structured intents, never arbitrary text or a shell command.
5. The returned intent is validated against that same schema and, if the model's
   confidence is high enough, dispatched to a hardcoded handler for that intent alone.
   Handlers execute through `subprocess` argument lists, `hyprctl` IPC, or D-Bus/MPRIS
   calls -- never by asking the model to produce a command to run directly.
6. Desktop notifications report what was heard and what happened, both on success and
   on failure (low confidence, unknown app, nothing to do, and so on).

Low-confidence results are refused rather than guessed, and results are cached briefly
so repeating the same command doesn't re-run the full classification step.

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
- **whisper.cpp** (via `pywhispercpp`) -- local speech-to-text, running the `base`
  model.
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
- **playerctl** -- MPRIS media control, used for play/pause/resume against Spotify.
- Python 3.14, Typer (developer CLI), httpx, cachetools.

## Keybinds

| Keybind | Action |
|---|---|
| `SUPER+ALT+V` | Trigger the voice pipeline (English) |
| `SUPER+ALT+B` | Reserved for Egyptian Arabic (see "Language support" below) |

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
| Speech-to-text (whisper.cpp, `base` model) | roughly 1.1-2.3 seconds |
| Intent classification (local LLM, GPU-resident) | roughly 2.1-2.6 seconds on average |
| Trailing silence before recording stops | 1.0 second |
| Action execution | under 100 milliseconds |

A full internal regression check across 54 representative commands, run directly
against the classification step, currently averages close to 2.5 seconds per command
with all 54 classified correctly. End-to-end, from the moment you stop speaking to the
result notification appearing, typically lands in the four-to-six-second range for a
short command.

Two points worth being explicit about:

- The classification step is bound by the local GPU's raw generation throughput for
  the chosen model, not by the size of the instructions given to it -- prompt length
  has been measured directly and is not the limiting factor.
- Repeating an identical command shortly after the first attempt is served from a
  short-lived cache rather than reclassified.

## Language support

English is fully supported today. Egyptian Arabic support is planned next: a
fine-tuned Arabic/Arabic-English model has already been selected for this, and the
`SUPER+ALT+B` keybind is already reserved for it, but the pipeline itself is not wired
up yet -- pressing it currently reports a clear "not supported yet" notification rather
than doing nothing silently.

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

## Project status

Built so far: the deterministic executor and safety gating, application discovery from
installed `.desktop` files, LLM-based intent classification with a response cache, the
full audio pipeline (capture, voice-activity detection, transcription), the warm
background daemon and its Unix-socket protocol, and the real Hyprland keybind
integration with a systemd `--user` service.

Not yet built: the Egyptian Arabic pipeline, a real confirmation flow for destructive
actions (package/system updates), broader hardening for long-term unattended use, web
search, and free-text file lookup.

## License

MIT
