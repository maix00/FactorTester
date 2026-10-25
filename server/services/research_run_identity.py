"""Dependency-light identity primitives for immutable ResearchRun specs."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


RUN_SPEC_VERSION = 4
NAUTILUS_RUN_SPEC_VERSION = 10


def run_spec_version_for_configuration(
    configuration: dict[str, Any], analyses: list[str],
) -> int:
    """Select the immutable RunSpec contract from its frozen execution backend."""
    configured_analyses = configuration.get("analyses")
    backtest = (
        configured_analyses.get("backtest")
        if isinstance(configured_analyses, dict) else None
    )
    execution = backtest.get("execution") if isinstance(backtest, dict) else None
    if (
        "backtest" in analyses
        and isinstance(execution, dict)
        and execution.get("backend") == "nautilus_trader"
    ):
        return NAUTILUS_RUN_SPEC_VERSION
    return RUN_SPEC_VERSION


def hash_run_spec(run_spec: dict[str, Any]) -> str:
    """Return the canonical immutable identity used by ResearchRun."""
    return hashlib.sha256(
        orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


__all__ = [
    "RUN_SPEC_VERSION", "NAUTILUS_RUN_SPEC_VERSION",
    "run_spec_version_for_configuration", "hash_run_spec",
]
