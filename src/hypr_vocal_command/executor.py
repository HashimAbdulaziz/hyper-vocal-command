"""Validates a raw intent envelope, applies safety gates, and dispatches to the registered handler."""

from typing import Any, cast

from pydantic import ValidationError

from .config import Config, load_config
from .registry import REGISTRY, ExecutionResult
from .schema import Envelope, parse_envelope
from .utils.notifier import notify
from .utils.telemetry import log_event


def execute(
    raw: dict[str, Any],
    config: Config | None = None,
    *,
    raw_llm_response: str | None = None,
    llm_latency_ms: float | None = None,
    transcript: str | None = None,
) -> ExecutionResult:
    config = config if config is not None else load_config()

    llm_context: dict[str, Any] = {}
    if raw_llm_response is not None:
        llm_context["raw_llm_response"] = raw_llm_response
    if llm_latency_ms is not None:
        llm_context["llm_latency_ms"] = llm_latency_ms
    if transcript is not None:
        llm_context["transcript"] = transcript

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
