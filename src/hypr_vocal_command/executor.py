"""Validates a raw intent envelope, applies safety gates, and dispatches to the registered handler."""

import difflib
from typing import Any, cast

from pydantic import ValidationError

from .config import Config, load_config, normalize_text
from .registry import REGISTRY, ExecutionResult
from .schema import Envelope, parse_envelope
from .utils.notifier import notify
from .utils.telemetry import log_event

# Slightly stricter than config.py's 0.75 alias-matching cutoff, tuned against real
# captured transcripts: at 0.75 the garbled tile word "الطايل" scored 0.77 against
# whatsapp's registered "الرسايل" and let a wrong close through. Every genuine
# mis-hearing this has to tolerate is registered verbatim as a surface form (so it
# scores 1.0 here), which is what makes the stricter bar safe.
_GROUNDING_CUTOFF = 0.80


def _app_name_is_grounded(app_name: str, transcript: str, config: Config) -> bool:
    """Whether `app_name` is actually supported by something the user said.

    The model sometimes answers with a familiar application that appears NOWHERE in the
    transcript -- real captured examples: "رجعني الوركز بيس اللي قبلها" ("take me back to
    the previous workspace") returned CLOSE_APP{chrome} and closed the browser, and
    "مفتح لينا ترمنة" ("open us a terminal") returned OPEN_APP{spotify}. Both logged as
    clean successes. Prompt rules alone did not stop this, so it is checked structurally:
    if none of the resolved app's registered names resembles anything in the transcript,
    the name was invented and the command must not run.

    Deliberately compares against the ALIAS's names rather than the raw `app_name`, so
    legitimate concept words still pass -- "المتصفح" grounds chrome, "الاديتور" grounds
    vscode, "putify" grounds spotify -- because each is a registered form of that app.
    """
    entry = config._resolve_app_entry(app_name)
    if entry is None:
        # Unresolvable anyway; the handler reports "Unknown app" with a clearer message
        # than this check could, so don't pre-empt it.
        return True

    _key, alias = entry
    text = normalize_text(transcript)
    if not text:
        return True  # nothing to check against (e.g. debug-execute with no transcript)

    words = text.split()
    for form in alias.surface_forms:
        normalized_form = normalize_text(form)
        if not normalized_form:
            continue
        if normalized_form in text:
            return True
        form_words = normalized_form.split()
        span = len(form_words)
        for start in range(len(words) - span + 1):
            window = " ".join(words[start : start + span])
            if difflib.SequenceMatcher(None, window, normalized_form).ratio() >= _GROUNDING_CUTOFF:
                return True
    return False


def execute(
    raw: dict[str, Any],
    config: Config | None = None,
    *,
    raw_llm_response: str | None = None,
    llm_latency_ms: float | None = None,
    transcript: str | None = None,
    language: str | None = None,
    path: str | None = None,
) -> ExecutionResult:
    config = config if config is not None else load_config()

    llm_context: dict[str, Any] = {}
    if raw_llm_response is not None:
        llm_context["raw_llm_response"] = raw_llm_response
    if llm_latency_ms is not None:
        llm_context["llm_latency_ms"] = llm_latency_ms
    if transcript is not None:
        llm_context["transcript"] = transcript
    if language is not None:
        # Recorded so a later log review can tell the English and Egyptian Arabic
        # pipelines apart per command, not just guess from the script of the transcript.
        llm_context["language"] = language
    if path is not None:
        # "fastpath" (fastpath.py matched deterministically, no Ollama call at all) or
        # "llm" (the normal classification path) -- lets a later log review tell which
        # commands actually got the instant response vs. paid the full LLM latency.
        llm_context["path"] = path

    try:
        envelope = cast(Envelope, parse_envelope(raw))
    except ValidationError as exc:
        result = ExecutionResult(ok=False, message=f"Invalid intent payload: {exc}")
        notify("hypr-vocal-command", result.message, urgency="critical")
        log_event({"stage": "validate", "raw": raw, "ok": False, "error": str(exc), **llm_context})
        return result

    spec = REGISTRY[envelope.intent]

    if envelope.confidence < config.confidence_threshold:
        result = ExecutionResult(
            ok=False,
            message=(
                f"Low confidence ({envelope.confidence:.2f}) for {envelope.intent}, "
                "not executing."
            ),
        )
        notify("hypr-vocal-command", result.message)
        log_event(
            {
                "stage": "gate",
                "intent": envelope.intent,
                "confidence": envelope.confidence,
                "ok": False,
                "reason": "low_confidence",
                **llm_context,
            }
        )
        return result

    spoken_app = getattr(envelope.args, "app_name", None)
    if (
        spoken_app is not None
        and transcript is not None
        and not _app_name_is_grounded(spoken_app, transcript, config)
    ):
        result = ExecutionResult(
            ok=False,
            message=f"Didn't act: nothing in what you said sounds like {spoken_app!r}.",
        )
        notify("hypr-vocal-command", result.message)
        log_event(
            {
                "stage": "gate",
                "intent": envelope.intent,
                "confidence": envelope.confidence,
                "ok": False,
                "reason": "app_name_not_grounded_in_transcript",
                "app_name": spoken_app,
                **llm_context,
            }
        )
        return result

    if spec.requires_confirmation:
        result = ExecutionResult(
            ok=False,
            message=(
                f"{envelope.intent} requires confirmation, which isn't implemented yet — "
                "not executing."
            ),
        )
        notify("hypr-vocal-command", result.message)
        log_event(
            {
                "stage": "gate",
                "intent": envelope.intent,
                "ok": False,
                "reason": "confirmation_required",
                **llm_context,
            }
        )
        return result

    result = spec.handler(envelope.args, config)
    notify("hypr-vocal-command", result.message, urgency="normal" if result.ok else "critical")
    log_event(
        {
            "stage": "execute",
            "intent": envelope.intent,
            "confidence": envelope.confidence,
            "args": envelope.args.model_dump(),
            "ok": result.ok,
            "message": result.message,
            **llm_context,
        }
    )
    return result
