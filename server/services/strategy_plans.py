"""Authoritative validation and normalization for user Strategy specs."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterable

from tools.cli.core.strategy_spec import StrategySpec, template_for
from tools.testers.backtest.engines.native.market_events import MarketFeedEventKind


_REQUIREMENT_FLAGS = {
    "needs_partial_fills",
    "needs_order_events",
    "needs_order_status_events",
    "needs_position_events",
    "needs_timer_events",
}


def normalize_strategy_plan(
    raw_specs: Any,
    *,
    uploaded_paths: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Freeze user declarations before a Run/Job is created.

    The CLI is a convenience validator; this function is the server authority
    and deliberately returns source-free metadata only.
    """
    if raw_specs in (None, []):
        return []
    if not isinstance(raw_specs, list):
        raise ValueError("strategy_specs must be an array")
    uploaded = {str(value).replace("\\", "/") for value in uploaded_paths}
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_specs:
        if not isinstance(raw, dict):
            raise ValueError("each strategy spec must be an object")
        try:
            spec = StrategySpec.from_mapping(raw)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if spec.strategy_id and not spec.strategy_id.isidentifier():
            raise ValueError("strategy_id must be a Python identifier")
        if spec.entrypoint and not spec.entrypoint.isidentifier():
            raise ValueError("strategy entrypoint must be a Python identifier")
        if spec.source_kind == "builtin":
            template = template_for(spec.source_name)
            kind = template.key
            required_fields = list(template.required_fields)
            required_data = list(template.required_data)
            callbacks = list(template.actor_callbacks)
        else:
            name = spec.source_name.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.startswith("strategies/"):
                raise ValueError("custom strategy source must be strategies/<path>.py")
            if name not in uploaded:
                raise ValueError(f"custom strategy source is not uploaded: {name}")
            kind = "custom"
            required_fields = list(spec.requirements.get("fields") or [])
            required_data = list(spec.requirements.get("data") or [])
            callbacks = []
        requirements = _normalize_requirements(spec.requirements)
        identity = spec.strategy_id
        if identity:
            if identity in seen_ids:
                raise ValueError(f"duplicate strategy_id: {identity}")
            seen_ids.add(identity)
        normalized = spec.normalized()
        normalized.update({
            "strategy_kind": kind,
            "required_fields": required_fields,
            "required_data": required_data,
            "actor_callbacks": callbacks,
            "requirements": requirements,
        })
        result.append(normalized)
    return result


def _normalize_requirements(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("strategy requirements must be an object")
    allowed = _REQUIREMENT_FLAGS | {"feed_events", "fields", "data"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("unknown strategy requirement: " + ", ".join(unknown))
    events = value.get("feed_events") or []
    if not isinstance(events, (list, tuple, set)):
        raise ValueError("strategy requirements feed_events must be an array")
    valid_events = {item.value for item in MarketFeedEventKind}
    normalized_events = []
    for event in events:
        name = str(event).strip().lower()
        if name not in valid_events:
            raise ValueError(f"unknown strategy feed event: {name}")
        if name not in normalized_events:
            normalized_events.append(name)
    result: dict[str, Any] = {"feed_events": sorted(normalized_events)}
    for key in _REQUIREMENT_FLAGS:
        if key in value:
            result[key] = bool(value[key])
    for key in ("fields", "data"):
        items = value.get(key) or []
        if not isinstance(items, (list, tuple, set)):
            raise ValueError(f"strategy requirements {key} must be an array")
        result[key] = sorted({str(item) for item in items if str(item).strip()})
    return result
