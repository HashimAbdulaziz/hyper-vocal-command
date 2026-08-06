"""Turns the flat `events.jsonl` telemetry log into a reviewable report of real voice
commands: what was said, what the pipeline decided, and what actually happened.

Why this exists: collecting every real-world mishearing/typo by hand doesn't scale --
Egyptian Arabic alone produced dozens of distinct garbled spellings for a handful of
words over one session. The intended workflow is to let the daemon run for a while
(a day, a week) and then run `hypr-vocal-command review-log` once to see everything it
heard and did, so misclassifications can be spotted and fixed in bulk instead of
reactively, one screenshot at a time.

Deliberately does NOT filter down to failures only. The two most dangerous bugs found
during this project's own development (opening the wrong app on a garbled name;
`killactive` firing instead of closing a named app) both logged with `ok: true` --
they looked like clean successes. A review technique that only surfaces `ok: false`
rows would have hidden exactly the mistakes that mattered most. Every command is
listed; heuristic flags exist only to draw the eye, never to hide a row.
"""

import datetime as dt
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import normalize_text

# Stages that correspond to exactly one real classification attempt against a real
# spoken transcript. "connection"-stage events (busy, disconnected, uid mismatch) carry
# no transcript/intent and aren't useful for judging "did the pipeline understand me" --
# they're counted separately in the summary but not listed as commands.
_COMMAND_STAGES = ("gate", "execute", "validate")

# How close to the confidence threshold, but still above it, counts as "worth a second
# look" even though it passed. Not a hard science -- a value tuned to flag genuinely
# marginal calls without flagging most of the log.
_LOW_MARGIN_BAND = 0.15


@dataclass(frozen=True)
class CommandRecord:
    timestamp: float
    stage: str
    language: str | None
    transcript: str
    intent: str | None
    confidence: float | None
    ok: bool
    message: str | None
    args: dict[str, Any]
    flags: tuple[str, ...] = ()

    @property
    def when(self) -> str:
        # Deliberately local time, no explicit tz -- this report is read by the one
        # person on the one machine that generated it, so local wall-clock time is the
        # useful display, not UTC.
        return dt.datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ006


def _load_raw_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # A partially-written line (e.g. daemon killed mid-write) shouldn't
                # sink review of every other real command in the file.
                continue
    return events


def load_command_records(
    path: Path, *, since: float | None = None
) -> list[CommandRecord]:
    """Read `events.jsonl` and return one record per real voice-command attempt,
    oldest first. `since` is a unix timestamp; events strictly older are dropped.

    Events from stages other than gate/execute/validate, or missing a `transcript`
    (pre-pipeline `debug-execute` calls, or a `validate` failure that never reached a
    transcript at all), are excluded -- they aren't a spoken command to review.
    """
    records = []
    for event in _load_raw_events(path):
        if event.get("stage") not in _COMMAND_STAGES:
            continue
        transcript = event.get("transcript")
        if not transcript:
            continue
        timestamp = event.get("timestamp", 0.0)
        if since is not None and timestamp < since:
            continue
        records.append(
            CommandRecord(
                timestamp=timestamp,
                stage=event["stage"],
                language=event.get("language"),
                transcript=transcript,
                intent=event.get("intent"),
                confidence=event.get("confidence"),
                ok=bool(event.get("ok")),
                message=event.get("message") or event.get("reason"),
                args=event.get("args", {}),
            )
        )
    records.sort(key=lambda r: r.timestamp)
    return records


def _flag_records(
    records: list[CommandRecord], *, confidence_threshold: float
) -> list[CommandRecord]:
    """Attach heuristic flags without removing or reordering anything -- flags are a
    reading aid, not a filter."""
    intents_by_text: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r.intent:
            intents_by_text[normalize_text(r.transcript)].add(r.intent)

    flagged = []
    for r in records:
        flags = []
        if not r.ok:
            flags.append("blocked")
        elif (
            r.confidence is not None
            and confidence_threshold <= r.confidence < confidence_threshold + _LOW_MARGIN_BAND
        ):
            # Passed the gate, but only just -- the kind of call that's most worth
            # double-checking actually matched what was meant.
            flags.append("low-margin-pass")
        if len(intents_by_text[normalize_text(r.transcript)]) > 1:
            # The same (normalized) thing said more than once resolved to different
            # intents across those occurrences -- a sign of model instability on this
            # exact phrasing, independent of whether any single occurrence looked fine.
            flags.append("inconsistent")
        flagged.append(
            CommandRecord(
                timestamp=r.timestamp,
                stage=r.stage,
                language=r.language,
                transcript=r.transcript,
                intent=r.intent,
                confidence=r.confidence,
                ok=r.ok,
                message=r.message,
                args=r.args,
                flags=tuple(flags),
            )
        )
    return flagged


def build_report(records: list[CommandRecord]) -> str:
    """Render a plain-text report: a summary block, then every command in
    chronological order. Meant to be read top-to-bottom in one sitting."""
    lines: list[str] = []

    if not records:
        return "No commands recorded in this window."

    total = len(records)
    ok_count = sum(1 for r in records if r.ok)
    by_intent = Counter(r.intent or "?" for r in records)
    by_language = Counter(r.language or "unknown" for r in records)
    flagged_counts = Counter(f for r in records for f in r.flags)

    lines.append(f"{total} commands from {records[0].when} to {records[-1].when}")
    lines.append(f"  ok: {ok_count}   blocked/failed: {total - ok_count}")
    lines.append(f"  by language: {dict(by_language)}")
    lines.append(f"  by intent: {dict(by_intent)}")
    if flagged_counts:
        lines.append(f"  flagged for review: {dict(flagged_counts)}")
    lines.append("")
    lines.append(
        "Every command is listed below, including ones that succeeded -- a wrong "
        "action can still log ok=true. [blocked] rows didn't execute at all; "
        "[low-margin-pass] and [inconsistent] rows executed but are worth a second "
        "look. Read the transcript against the message/args and confirm it actually "
        "matches what was meant."
    )
    lines.append("")

    for r in records:
        flag_str = f" [{', '.join(r.flags)}]" if r.flags else ""
        lang = r.language or "?"
        conf = f"{r.confidence:.2f}" if r.confidence is not None else "?"
        lines.append(
            f"{r.when}  ({lang})  {r.transcript!r}\n"
            f"  -> {r.intent or '?'} conf={conf} args={r.args}\n"
            f"  ok={r.ok} {r.message or ''}{flag_str}"
        )

    return "\n".join(lines)


def review(
    *, path: Path, since: float | None = None, confidence_threshold: float = 0.6
) -> str:
    """Load, flag, and render -- the one call `cli.py`'s `review-log` command needs."""
    records = load_command_records(path, since=since)
    records = _flag_records(records, confidence_threshold=confidence_threshold)
    return build_report(records)
