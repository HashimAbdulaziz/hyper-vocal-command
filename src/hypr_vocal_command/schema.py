"""Builds the discriminated-union intent envelope schema from the registry.

This is the single source of truth shared by (a) the JSON Schema handed to the LLM's
structured-output `format` field, and (b) the validator that parses its response — an
intent can never exist in one without existing in the other.
"""

from typing import Annotated, Literal, Protocol, Union

from pydantic import BaseModel, Field, TypeAdapter, create_model

from .registry import REGISTRY


class Envelope(Protocol):
    """Structural shape of any parsed intent envelope (each is a dynamically generated model)."""

    schema_version: int
    intent: str
    confidence: float
    args: BaseModel


def _build_envelope_variant(
    name: str, args_model: type[BaseModel], *, include_schema_version: bool
) -> type[BaseModel]:
    # intent is required (no default) rather than merely constant: Ollama's JSON-Schema->
    # GBNF grammar treats non-required fields as freely omittable, and empirically the
    # model exploits that to drop `intent` entirely or leave it inconsistent with `args` —
    # see Phase 3 notes. Marking it required makes the grammar force its presence.
    #
    # schema_version is deliberately NOT part of the schema the LLM generates against
    # (include_schema_version=False, used for envelope_json_schema()) -- it's a purely
    # internal versioning concern the LLM has no way to usefully reason about, and asking
    # it to produce a fixed literal on every single call was pure wasted generation cost
    # (measured: ~40-55ms per output token on this hardware, so every unnecessary token
    # is a direct, real latency cost). It's injected by the LLM client after parsing the
    # model's response instead, then validated normally via parse_envelope() (which
    # always uses include_schema_version=True) -- same validation guarantee, fewer
    # tokens the model has to spend generating a constant it can't get meaningfully wrong
    # anyway once it's not asked to produce it at all.
    fields: dict[str, object] = {}
    if include_schema_version:
        fields["schema_version"] = (Literal[1], ...)
    fields["intent"] = (Literal[name], ...)
    fields["confidence"] = (float, Field(ge=0.0, le=1.0))
    fields["args"] = (args_model, ...)
    return create_model(f"{name}Envelope", **fields)  # type: ignore[call-overload]


def build_envelope_adapter(*, include_schema_version: bool = True) -> TypeAdapter:
    if not REGISTRY:
        raise RuntimeError("cannot build the intent schema: the registry is empty")

    variants = [
        _build_envelope_variant(name, spec.args_model, include_schema_version=include_schema_version)
        for name, spec in REGISTRY.items()
    ]

    union: object = (
        variants[0]
        if len(variants) == 1
        else Annotated[Union[tuple(variants)], Field(discriminator="intent")]  # noqa: UP007
    )
    return TypeAdapter(union)


def parse_envelope(raw: dict) -> BaseModel:
    return build_envelope_adapter(include_schema_version=True).validate_python(raw)


def envelope_json_schema() -> dict:
    """The schema handed to the LLM's structured-output `format` field -- deliberately
    excludes schema_version (see _build_envelope_variant); the LLM client injects it
    afterward, before the response ever reaches parse_envelope()'s full validation."""
    return build_envelope_adapter(include_schema_version=False).json_schema()
