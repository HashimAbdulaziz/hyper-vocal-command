"""Path containment check shared anywhere a filesystem path is derived from untrusted input."""

from pathlib import Path


def resolve_within(candidate: str | Path, allowed_roots: list[Path]) -> Path | None:
    try:
        resolved = Path(candidate).expanduser().resolve()
    except OSError:
        return None

    for root in allowed_roots:
        root_resolved = root.expanduser().resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    return None
