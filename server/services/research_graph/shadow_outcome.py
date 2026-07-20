"""Canonical, decision-relevant Job outcomes for shadow comparison."""

from __future__ import annotations

from typing import Any

import orjson

from server.services.research_graph.protocol import json_hash


_OPERATIONAL_RUNTIME_CODES = frozenset({
    "backtest_flow_profile",
    "backtest_result_assembly_profile",
})
_VOLATILE_RESULT_FIELDS = frozenset({
    "full_result_bytes",
    "run_id",
})


def canonical_result_summary(value: Any) -> dict[str, Any]:
    """Remove run identity and pure profiling from a result summary."""
    result = _json_object(value, label="result summary")
    canonical = {
        key: item
        for key, item in result.items()
        if key not in _VOLATILE_RESULT_FIELDS
    }
    runtime_rows = canonical.get("runtime_info_rows")
    if runtime_rows is not None:
        if not isinstance(runtime_rows, list):
            raise ValueError("result summary runtime_info_rows must be a list")
        canonical["runtime_info_rows"] = [
            row for row in runtime_rows
            if not (
                isinstance(row, dict)
                and row.get("code") in _OPERATIONAL_RUNTIME_CODES
            )
        ]
    return canonical


def canonical_terminal_assurance(value: Any) -> dict[str, Any]:
    """Retain assurance semantics while replacing its raw-result digest."""
    assurance = _json_object(value, label="terminal assurance")
    return {
        key: item
        for key, item in assurance.items()
        if key != "result_summary_hash"
    }


def canonical_json_hash(value: dict[str, Any]) -> str:
    return json_hash(value)


def _json_object(value: Any, *, label: str) -> dict[str, Any]:
    try:
        decoded = orjson.loads(value) if isinstance(value, (str, bytes)) else value
    except orjson.JSONDecodeError as exc:
        raise ValueError(f"{label} must be a valid JSON object") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be a JSON object")
    return decoded
