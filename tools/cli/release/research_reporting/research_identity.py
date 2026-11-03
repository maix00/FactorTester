"""Research references retained across native creation and legacy migration."""
from __future__ import annotations

import re

_RESEARCH_REF = re.compile(r"(?:research:v1:[A-Za-z0-9_-]{24,128}|research:migrated:[0-9a-f]{32})")


def is_research_ref(value: object) -> bool:
    """Validate an opaque identity without rewriting its prefix or owner."""
    return isinstance(value, str) and _RESEARCH_REF.fullmatch(value) is not None
