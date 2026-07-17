"""Importable worker runners that derive compact plans from frozen job specs."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


def _cache_keys(spec: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    selections = spec.get("product_selections") or {}
    if isinstance(selections, dict):
        values = selections.values()
    elif isinstance(selections, list):
        values = selections
    else:
        values = ()
    for selection in values:
        if not isinstance(selection, dict):
            continue
        for path in selection.get("selected_paths") or selection.get("paths") or ():
            if not isinstance(path, dict):
                continue
            product = str(path.get("product") or path.get("symbol") or "").strip()
            source = str(path.get("source") or path.get("data_source") or "").strip()
            frequency = str(path.get("frequency") or path.get("freq") or "").strip()
            if product:
                keys.add(":".join((product, source or "auto", frequency or "auto")))
    return sorted(keys)


def plan_job(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    """Validate a frozen job spec and emit a bounded execution plan."""
    spec = payload.get("job_spec")
    if not isinstance(spec, dict):
        raise ValueError("job_spec must be an object")
    if cancel_event.is_set():
        sink.emit_error("planning cancelled", cancelled=True)
        return
    runner_path = str(payload.get("runner_path") or "").strip()
    if not runner_path:
        raise ValueError("runner_path is required")
    raw = orjson.dumps(spec, option=orjson.OPT_SORT_KEYS)
    plan = {
        "plan_version": 1,
        "job_spec_hash": hashlib.sha256(raw).hexdigest(),
        "runner_path": runner_path,
        "cache_keys": _cache_keys(spec),
        "requested_start": spec.get("start_date") or spec.get("run_start"),
        "requested_end": spec.get("end_date") or spec.get("run_end"),
    }
    sink.emit_result({
        "success": True,
        "plan": plan,
        "notices": [],
        "requires_confirmation": False,
    })
