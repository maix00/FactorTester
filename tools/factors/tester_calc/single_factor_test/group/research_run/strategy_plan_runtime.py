"""Resolve and preflight frozen Strategy plans inside the native runner."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from tools.testers.backtest.engines.native.market_events import MarketFeedEventKind
from tools.testers.backtest.engines.native.strategy import Strategy, overridden_strategy_callbacks
from tools.testers.backtest.engines.native.strategy_hooks import (
    ExecutionCapabilities,
    StrategyRequirements,
    validate_strategy_capabilities,
)


def strategy_plan_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("strategy_plan")
    if value is None:
        value = payload.get("strategy_specs")
    return [item for item in (value or []) if isinstance(item, dict)]


def strategy_aliases_for_plan(plan: list[dict[str, Any]], available_aliases: list[str]) -> dict[int, str]:
    available = set(map(str, available_aliases))
    assigned: dict[int, str] = {}
    used: set[str] = set()
    for index, spec in enumerate(plan):
        identity = str(spec.get("strategy_id") or "").strip()
        if not identity:
            source_name = str(spec.get("source_name") or spec.get("source") or "")
            identity = PurePosixPath(source_name.split(":", 1)[-1]).stem
            if identity not in available and len(plan) == 1 and len(available) == 1:
                identity = next(iter(available))
        if identity not in available:
            raise ValueError(f"strategy {identity!r} is not declared by the backtest")
        if identity in used:
            raise ValueError(f"multiple strategy specs target {identity!r}")
        used.add(identity)
        assigned[index] = identity
    return assigned


def activate_strategy_plan(settings_by_alias: dict[str, dict[str, Any]], plan: list[dict[str, Any]], aliases: dict[int, str]) -> dict[str, dict[str, Any]]:
    resolved = {str(alias): dict(settings) for alias, settings in settings_by_alias.items()}
    for index, spec in enumerate(plan):
        alias = aliases[index]
        kind = str(spec.get("strategy_kind") or "custom")
        resolved[alias]["strategy_kind"] = kind
        resolved[alias]["strategy_intent_mode"] = kind
        resolved[alias]["_strategy_plan"] = dict(spec)
    return apply_custom_strategy_overrides(resolved, plan, aliases)


def apply_custom_strategy_overrides(
    settings_by_alias: dict[str, dict[str, Any]],
    plan: list[dict[str, Any]],
    aliases: dict[int, str],
    *,
    overrides: dict[str, Any] | None = None,
    product_mask: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply the nested custom-strategy scope without widening other strategies."""
    normalized_overrides = dict(overrides or {})
    normalized_products = tuple(
        dict.fromkeys(str(value).strip() for value in (product_mask or ()) if str(value).strip())
    )
    for index, spec in enumerate(plan):
        if str(spec.get("strategy_kind") or "custom") != "custom":
            continue
        alias = aliases[index]
        resolved = settings_by_alias[alias]
        resolved.update(normalized_overrides)
        if normalized_products:
            resolved["product_mask_names"] = normalized_products
    return settings_by_alias


def validate_strategy_plan_capabilities(payload: dict[str, Any], plan: list[dict[str, Any]], objects: dict[str, Strategy]) -> None:
    declared = {str(item).lower() for item in (payload.get("market_feed_events") or [])}
    valid = {kind.value for kind in MarketFeedEventKind}
    available_feed = frozenset(MarketFeedEventKind(item) for item in declared if item in valid)
    for index, spec in enumerate(plan):
        alias = str(spec.get("strategy_id") or "")
        actor = objects.get(alias) or (next(iter(objects.values())) if len(objects) == 1 else None)
        callbacks = overridden_strategy_callbacks(actor) if actor is not None else frozenset()
        event_by_callback = {
            "on_quote": MarketFeedEventKind.QUOTE,
            "on_trade": MarketFeedEventKind.TRADE,
            "on_book_delta": MarketFeedEventKind.BOOK_DELTA,
            "on_book_snapshot": MarketFeedEventKind.BOOK_SNAPSHOT,
        }
        requirements = dict(spec.get("requirements") or {})
        feed_events = set(requirements.get("feed_events") or [])
        feed_events.update(event.value for name, event in event_by_callback.items() if name in callbacks)
        flags = {key: bool(requirements.get(key)) for key in (
            "needs_partial_fills", "needs_order_events", "needs_order_status_events",
            "needs_position_events", "needs_timer_events",
        )}
        flags["needs_timer_events"] |= "on_timer" in callbacks
        flags["needs_order_events"] |= any(name.startswith("on_order_") for name in callbacks)
        flags["needs_position_events"] |= any(name.startswith("on_position_") for name in callbacks)
        report = validate_strategy_capabilities(
            StrategyRequirements(feed_events=frozenset(MarketFeedEventKind(item) for item in feed_events), **flags),
            ExecutionCapabilities(feed_events=available_feed, partial_fills=True, order_events=True,
                                  order_status_events=True, position_events=True, timer_events=True),
        )
        if not report["ok"]:
            raise ValueError(f"strategy {alias or index} capability check failed: " + "; ".join(report["errors"]))
