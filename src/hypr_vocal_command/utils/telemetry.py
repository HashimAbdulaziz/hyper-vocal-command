"""Structured JSONL event logging, one line per pipeline stage/invocation."""

import json
import os
import time
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    xdg_state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg_state_home) / "hypr-vocal-command"


def log_event(event: dict[str, Any]) -> None:
    path = _state_dir() / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": time.time(), **event}
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
