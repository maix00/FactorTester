"""Server-derived sample-scope identity for exposure-aware TrialPlan binding."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson


_UNIVERSE_KEYS = {"paths", "products", "selected_paths"}
_CONTEXT_KEYS = {
    "end_time",
    "frequency",
    "ic_lag",
    "return_price_basis",
    "signal_freq",
    "start_time",
    "time_precision",
    "timezone",
}
_COSMETIC_KEYS = {"desc", "description", "label"}


def derive_sample_identity(run_spec: dict[str, Any]) -> dict[str, Any]:
    """Hash one exact date/universe scope without assigning a sample role."""
    if not isinstance(run_spec, dict):
        raise ValueError("RunSpec must be an object")
    starts: set[str] = set()
    ends: set[str] = set()
    universes: list[Any] = []
    context: list[tuple[str, Any]] = []
    _collect_scope(
        run_spec,
        path="run_spec",
        starts=starts,
        ends=ends,
        universes=universes,
        context=context,
    )
    if not starts or not ends:
        raise ValueError(
            "RunSpec cannot derive sample identity without start/end dates"
        )
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError(
            "RunSpec sample identity requires one unambiguous date range"
        )
    if not universes:
        raise ValueError(
            "RunSpec cannot derive sample identity without product scope"
        )
    sample_start = next(iter(starts))
    sample_end = next(iter(ends))
    if sample_start > sample_end:
        raise ValueError("RunSpec sample date range is invalid")
    normalized_universes = _deduplicate(universes)
    universe_hash = _hash(normalized_universes)
    sample_basis = {
        "schema_version": 1,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "universe_hash": universe_hash,
    }
    return {
        **sample_basis,
        "sample_hash": _hash(sample_basis),
        "design_context_hash": _hash(sorted(context)),
        "authority": "server_derived_scope_v1",
        "limitations": [
            "data_snapshot_identity_not_bound",
            "external_result_access_not_observable",
            "partial_universe_overlap_not_detected",
        ],
    }


def _collect_scope(
    value: Any,
    *,
    path: str,
    starts: set[str],
    ends: set[str],
    universes: list[Any],
    context: list[tuple[str, Any]],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key == "start_date" and isinstance(item, str) and item:
                starts.add(item)
            elif key == "end_date" and isinstance(item, str) and item:
                ends.add(item)
            elif key in _UNIVERSE_KEYS and isinstance(item, list) and item:
                universes.append(_semantic_value(item))
            elif key in _CONTEXT_KEYS:
                context.append((key, _semantic_value(item)))
            _collect_scope(
                item,
                path=child_path,
                starts=starts,
                ends=ends,
                universes=universes,
                context=context,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_scope(
                item,
                path=f"{path}[{index}]",
                starts=starts,
                ends=ends,
                universes=universes,
                context=context,
            )


def _semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items())
            if str(key) not in _COSMETIC_KEYS
        }
    if isinstance(value, list):
        normalized = [_semantic_value(item) for item in value]
        return sorted(normalized, key=_encoded)
    return value


def _deduplicate(values: list[Any]) -> list[Any]:
    by_payload = {_encoded(value): value for value in values}
    return [by_payload[key] for key in sorted(by_payload)]


def _encoded(value: Any) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _hash(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()
