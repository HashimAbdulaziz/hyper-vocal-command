"""UNRECOGNIZED: the safety-valve intent for input that doesn't match any real action.

Grammar-constrained decoding forces the LLM to output *some* valid enum value even for
nonsense or adversarial input — without this explicit escape hatch, such input could get
coerced into a real action intent instead.
"""

from pydantic import BaseModel

from ..config import Config
from ..registry import ExecutionResult, intent_handler


class UnrecognizedArgs(BaseModel):
    pass


@intent_handler(
    "UNRECOGNIZED",
    UnrecognizedArgs,
    description=(
        "The input doesn't clearly match any of the above, is unrelated to system "
        "commands, or is ambiguous."
    ),
)
def unrecognized(args: UnrecognizedArgs, config: Config) -> ExecutionResult:
    return ExecutionResult(ok=False, message="Sorry, I didn't understand that.")
