"""Dependency-light identity primitives for immutable ResearchRun specs."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


RUN_SPEC_VERSION = 3


def hash_run_spec(run_spec: dict[str, Any]) -> str:
    """Return the canonical immutable identity used by ResearchRun."""
    return hashlib.sha256(
        orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


__all__ = ["RUN_SPEC_VERSION", "hash_run_spec"]
