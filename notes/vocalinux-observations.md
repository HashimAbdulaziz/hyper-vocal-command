# Vocalinux observations (for your future contribution)

Running notes on anything relevant to jatinkrmalik/vocalinux issues #476, #478, #607, #614
(text-injection backend selection on wlroots/tiling compositors), gathered incidentally
while building hypr-vocal-command on this exact Hyprland setup. Not filed upstream by me --
these are evidence for you to use when you contribute yourself.

## 2026-08-03 -- Phase 5 (audio ingestion) research

**Session environment on this machine:**
- `XDG_CURRENT_DESKTOP=Hyprland`, `XDG_SESSION_DESKTOP=Hyprland`, `DESKTOP_SESSION=hyprland-uwsm`
- `ibus-daemon` not currently running; `ibus-wayland` (the bridge mentioned in #607) is not installed
- `wtype` and `ydotool` are both installed and available
- vocalinux installed version: 0.14.2 (`~/.local/share/vocalinux`)

**Finding: the core #476/#478 bug already appears fixed for Hyprland specifically, in the
installed version.**

`src/vocalinux/text_injection/text_injector.py` (`_wayland_compositor_bridges_ibus()`,
~line 197) now maintains an explicit denylist of "IBus-unbridged" wlroots/smithay
compositors -- `cosmic, sway, hyprland, wayfire, river, niri, labwc, weston` -- with a
comment explicitly describing the exact symptom from #476/#478: *"an IBus engine's
commit_text() reaches only XWayland and GTK/Qt apps that load the IBus IM module, while
native apps ... receive nothing -- the injection appears to succeed but the text is
silently dropped."* On Hyprland specifically, this function returns `False`, meaning
vocalinux should automatically prefer `wtype`/`ydotool` over IBus here -- exactly the
behavior #476 originally asked for, just via auto-detection instead of a user-facing
config override.

This lines up with the earlier finding (from the maintainer's own comment thread) that a
commit "5d ago" (`feat(text-injection): use IBus on unbridged compositors when
ibus-wayland runs`) was landed addressing #607/#614 -- this denylist logic looks like part
of that same effort, and by extension likely also resolves #478's specific complaint.

**What's probably still open, worth checking before you file/comment:**
- #476's *original* ask was an explicit user-facing override (an `injection_backend` key
  in config.json) so a user isn't at the mercy of auto-detection -- e.g. if a *future*
  compositor or an unusual setup isn't on the denylist yet, or auto-detection guesses
  wrong. The auto-detection fix doesn't necessarily close that explicit-override request;
  it might be a legitimately separate, still-valid ask. Worth checking the issue's current
  state (open/closed, any linked PR) before assuming it's fully resolved.
- Have not yet live-tested actual dictation output landing in a native Wayland app (e.g.
  kitty) vs an XWayland one on this machine to visually confirm the fix behaves as the
  code implies -- the above is read from source, not yet observed end-to-end. Worth doing
  once there's a natural opportunity (needs a live spoken utterance, not synthesized TTS,
  to be a fair test of vocalinux's own pipeline).

## Still to do
- Live-observe vocalinux dictation actually typing into kitty and a native GTK app on this
  session, to convert the source-reading finding above into a directly-observed one.
- Check the real current state of issues #476, #478, #607, #614 (open/closed, linked PRs)
  before drafting anything.
