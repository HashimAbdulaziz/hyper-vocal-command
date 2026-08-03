"""Intent registry: single source of truth for the LLM schema and the executor dispatch table."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .config import Config


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    message: str


# Storage type is intentionally `Any` for the args parameter: each registered handler is
# typed against its own specific args model (e.g. OpenTerminalArgs), and Callable parameter
# types are contravariant, so a precise BaseModel-subtype signature here would reject every
# real handler. The registry's own machinery (schema.py + executor.py) guarantees each
# handler only ever receives an instance of the args_model it was registered with.
HandlerFn = Callable[[Any, Config], ExecutionResult]


@dataclass(frozen=True)
class IntentSpec:
    name: str
    args_model: type[BaseModel]
    handler: HandlerFn
    requires_confirmation: bool = False
    description: str = ""


REGISTRY: dict[str, IntentSpec] = {}


def intent_handler(
    name: str,
    args_model: type[BaseModel],
    *,
    requires_confirmation: bool = False,
    description: str = "",
) -> Callable[[HandlerFn], HandlerFn]:
    def decorator(fn: HandlerFn) -> HandlerFn:
        if name in REGISTRY:
            raise RuntimeError(f"intent '{name}' is already registered")
        REGISTRY[name] = IntentSpec(
            name=name,
            args_model=args_model,
            handler=fn,
            requires_confirmation=requires_confirmation,
            description=description,
        )
        return fn

    return decorator


def validate_startup(expected: Iterable[str]) -> None:
    if not REGISTRY:
        raise RuntimeError("intent registry is empty")
    missing = set(expected) - REGISTRY.keys()
    if missing:
        raise RuntimeError(
            f"intent registry is missing handlers for: {sorted(missing)} "
            "(a handler module probably wasn't imported)"
        )
