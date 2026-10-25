"""Freeze native Nautilus venues and strategy-to-venue routes.

Nautilus owns one simulated account per configured venue. Strategy instances
are independent actors in the same engine and route orders by InstrumentId;
they are not account owners and do not get a private copy of venue cash or
matching liquidity.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from server.services.nautilus_bridge.native_configuration import freeze_native_venue_config


class UnsupportedVenuePlan(ValueError):
    """The configured venues or strategy routes cannot be represented natively."""


_ACCOUNT_TYPES = frozenset({"CASH", "MARGIN", "BETTING"})
_OMS_TYPES = frozenset({"NETTING", "HEDGING"})


def freeze_native_venues(
    backtest: Mapping[str, Any], settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile venue cards and strategy bindings into the RunSpec contract.

    Authoring rows may use ``venue_id`` and a single amount/currency pair.
    Frozen rows use Nautilus field names and its ``starting_balances`` string
    format. Product selections remain references; the execution builder later
    verifies their resolved InstrumentIds against these venue routes.
    """
    raw_venues = backtest.get("venues")
    if not isinstance(raw_venues, list) or not raw_venues:
        raise UnsupportedVenuePlan("define at least one Nautilus Venue")

    default_currency = _text(settings.get("base_currency"), "base_currency").upper()
    initial_capital = _positive_decimal(
        settings.get("initial_capital_major"), "initial_capital_major",
    )
    venues: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for raw in raw_venues:
        if not isinstance(raw, Mapping):
            raise UnsupportedVenuePlan("venues entries must be objects")
        name = _text(raw.get("name") or raw.get("venue_id"), "venues.name").upper()
        if name in by_name:
            raise UnsupportedVenuePlan(f"duplicate Nautilus Venue {name}")
        account_type = str(raw.get("account_type") or "MARGIN").strip().upper()
        if account_type not in _ACCOUNT_TYPES:
            raise UnsupportedVenuePlan(
                f"venue {name} account_type must be CASH, MARGIN, or BETTING",
            )
        oms_type = str(raw.get("oms_type") or "NETTING").strip().upper()
        if oms_type not in _OMS_TYPES:
            raise UnsupportedVenuePlan(f"venue {name} oms_type must be NETTING or HEDGING")
        base_currency = str(raw.get("base_currency") or default_currency).strip().upper()
        if not base_currency:
            raise UnsupportedVenuePlan(f"venue {name} requires base_currency")
        balances = _starting_balances(raw, default_currency)
        if not balances and len(raw_venues) == 1:
            balances = [f"{initial_capital} {default_currency}"]
        if not balances:
            raise UnsupportedVenuePlan(
                f"venue {name} requires starting_balances; total RunSpec capital is not copied to every venue",
            )
        currencies = {item.rsplit(" ", 1)[1] for item in balances}
        if currencies != {default_currency} or base_currency != default_currency:
            raise UnsupportedVenuePlan(
                f"venue {name} must use the RunSpec base_currency until cross-currency initial-capital valuation is configured",
            )
        native_config = raw.get("native_config")
        # One-time authoring bridge for existing drafts. New UI state stores
        # these options on each Venue, where Nautilus actually applies them.
        if native_config is None:
            legacy_venue_options = settings.get("nautilus_venue")
            capacity_policy = str(settings.get("nt_capacity_policy") or "unconstrained")
            inherited_capacity = {
                "liquidity_consumption": capacity_policy in {"bar_volume", "recorded_depth"},
                "price_protection_points": settings.get("nt_price_protection_points", 0),
            }
            if legacy_venue_options is not None:
                if not isinstance(legacy_venue_options, Mapping):
                    raise UnsupportedVenuePlan("nautilus_venue must be an object")
                inherited_capacity.update({
                    "bar_volume_weights_bps": legacy_venue_options.get("bar_volume_weights_bps"),
                    "bar_volume_remainder_to": legacy_venue_options.get(
                        "bar_volume_remainder_to", "close",
                    ),
                })
            native_config = inherited_capacity
        try:
            frozen_native_config = freeze_native_venue_config(native_config)
        except ValueError as exc:
            raise UnsupportedVenuePlan(str(exc)) from exc
        row = {
            "name": name,
            "account_type": account_type,
            "oms_type": oms_type,
            "starting_balances": balances,
            "base_currency": base_currency,
            "native_config": frozen_native_config,
        }
        by_name[name] = row
        venues.append(row)

    total = sum(
        (Decimal(item.split(" ", 1)[0]) for venue in venues for item in venue["starting_balances"]),
        Decimal(0),
    )
    if total != initial_capital:
        raise UnsupportedVenuePlan(
            "venue starting_balances must sum to initial_capital_major; each venue account is isolated",
        )

    groups = [item for item in backtest.get("groups", ()) if isinstance(item, Mapping)]
    if not groups:
        raise UnsupportedVenuePlan("at least one strategy instance is required")
    groups_by_id: dict[str, Mapping[str, Any]] = {}
    for group in groups:
        strategy_id = _text(group.get("id"), "groups.id")
        if strategy_id in groups_by_id:
            raise UnsupportedVenuePlan(f"duplicate strategy instance {strategy_id}")
        groups_by_id[strategy_id] = group

    raw_bindings = backtest.get("strategy_venue_bindings") or []
    if not isinstance(raw_bindings, list):
        raise UnsupportedVenuePlan("strategy_venue_bindings must be an array")
    routes: dict[str, dict[str, Any]] = {}
    for raw in raw_bindings:
        if not isinstance(raw, Mapping):
            raise UnsupportedVenuePlan("strategy_venue_bindings entries must be objects")
        strategy_id = _text(raw.get("strategy_id"), "strategy_venue_bindings.strategy_id")
        if strategy_id not in groups_by_id:
            raise UnsupportedVenuePlan(f"strategy route references unknown strategy {strategy_id}")
        if strategy_id in routes:
            raise UnsupportedVenuePlan(f"strategy {strategy_id} has duplicate venue routes")
        venue_ids = raw.get("venue_ids")
        if not isinstance(venue_ids, list) or not venue_ids:
            raise UnsupportedVenuePlan(f"strategy {strategy_id} must bind at least one Venue")
        normalized_ids = sorted({_text(item, "strategy_venue_bindings.venue_ids").upper() for item in venue_ids})
        unknown = set(normalized_ids) - set(by_name)
        if unknown:
            raise UnsupportedVenuePlan(
                f"strategy {strategy_id} references unconfigured Venue(s): {', '.join(sorted(unknown))}",
            )
        scope = _group_scope_ref(groups_by_id[strategy_id])
        if not scope:
            raise UnsupportedVenuePlan(f"strategy {strategy_id} needs a frozen product-scope reference")
        routes[strategy_id] = {
            "strategy_id": strategy_id,
            "venue_ids": normalized_ids,
            "product_scope_refs": [scope],
        }

    missing_routes = set(groups_by_id) - set(routes)
    if missing_routes:
        raise UnsupportedVenuePlan(
            "bind every strategy instance to one or more Nautilus Venues: "
            + ", ".join(sorted(missing_routes)),
        )
    unused_venues = set(by_name) - {
        venue_id for route in routes.values() for venue_id in route["venue_ids"]
    }
    if unused_venues:
        raise UnsupportedVenuePlan(
            "every configured Venue must be bound to a strategy: "
            + ", ".join(sorted(unused_venues)),
        )

    return {
        "version": 1,
        "venues": sorted(venues, key=lambda item: item["name"]),
        "strategy_bindings": [routes[key] for key in sorted(routes)],
        "account_model": "one_account_per_venue",
        "execution_model": "one_backtest_engine_per_run",
        "shared_market_data": True,
    }


def _starting_balances(raw: Mapping[str, Any], default_currency: str) -> list[str]:
    value = raw.get("starting_balances")
    if value is None:
        amount = raw.get("starting_balance")
        if amount in (None, ""):
            return []
        currency = str(raw.get("currency") or default_currency).strip().upper()
        value = [f"{amount} {currency}"]
    if not isinstance(value, list) or not value:
        raise UnsupportedVenuePlan("venues.starting_balances must be a nonempty array")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise UnsupportedVenuePlan("venues.starting_balances entries must be Nautilus Money strings")
        parts = item.strip().replace(",", "").rsplit(None, 1)
        if len(parts) != 2:
            raise UnsupportedVenuePlan("starting balance format is '<amount> <currency>'")
        amount = _positive_decimal(parts[0], "venues.starting_balances")
        currency = _text(parts[1], "venues.starting_balances.currency").upper()
        if currency in seen:
            raise UnsupportedVenuePlan(f"duplicate starting balance currency {currency}")
        seen.add(currency)
        result.append(f"{amount} {currency}")
    return sorted(result, key=lambda item: item.rsplit(" ", 1)[1])


def _group_scope_ref(group: Mapping[str, Any]) -> str:
    selection = group.get("product_path_selection")
    candidates = [
        group.get("product_path_selection_id"),
        group.get("product_scope_ref"),
        group.get("product_group_ref"),
    ]
    if isinstance(selection, Mapping):
        candidates = [
            selection.get("product_path_selection_id"), selection.get("selection_id"),
            selection.get("id"), *candidates,
        ]
    return next((str(item).strip() for item in candidates if str(item or "").strip()), "")


def _text(value: object, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise UnsupportedVenuePlan(f"{field} must be nonempty")
    return result


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise UnsupportedVenuePlan(f"{field} must be a positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise UnsupportedVenuePlan(f"{field} must be a positive decimal")
    return amount


__all__ = ["UnsupportedVenuePlan", "freeze_native_venues"]
