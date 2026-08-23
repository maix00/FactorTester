"""Execution and portfolio projections derived from retained replay facts."""

from __future__ import annotations

from typing import Any


def engine_result(source: dict[str, Any]) -> dict[str, Any]:
    direct = source.get("engine_result")
    if isinstance(direct, dict):
        return direct
    retained = source.get("group_execution")
    if isinstance(retained, dict) and isinstance(retained.get("engine_result"), dict):
        return retained["engine_result"]
    return {}


def order_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    return _audit_rows(source, "orders")


def fill_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    audit = source.get("order_audit") or {}
    strategies = audit.get("strategies") if isinstance(audit, dict) else {}
    rows: list[dict[str, Any]] = []
    for strategy, payload in (strategies or {}).items():
        if not isinstance(payload, dict):
            continue
        settlements = {
            str(item.get("fill_id")): item
            for item in payload.get("settlements") or ()
            if isinstance(item, dict) and item.get("fill_id")
        }
        for item in payload.get("fills") or ():
            if not isinstance(item, dict):
                continue
            settlement = settlements.get(str(item.get("fill_id"))) or {}
            cash_before = _number(settlement.get("cash_before"))
            cash_after = _number(settlement.get("cash_after"))
            margin_before = _number(settlement.get("margin_before"))
            margin_after = _number(settlement.get("margin_after"))
            dimensions = {
                key: settlement.get(key, item.get(key))
                for key in (
                    "account_id", "account_ref", "account", "ledger_id", "ledger",
                    "cash_pool_id", "cash_pool", "pool_id",
                    "account_currency", "ledger_currency", "currency",
                    "cash_pool_base_currency", "pool_base_currency", "base_currency",
                )
                if settlement.get(key, item.get(key)) not in (None, "")
            }
            rows.append({
                "strategy": str(strategy),
                **item,
                **dimensions,
                "realized_pnl": settlement.get("realized_pnl"),
                "cash_before": settlement.get("cash_before"),
                "cash_after": settlement.get("cash_after"),
                "cash_change": (
                    cash_after - cash_before
                    if cash_before is not None and cash_after is not None else None
                ),
                "margin_before": settlement.get("margin_before"),
                "margin_after": settlement.get("margin_after"),
                "margin_change": (
                    margin_after - margin_before
                    if margin_before is not None and margin_after is not None else None
                ),
            })
    return rows


def cash_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, portfolio in _portfolios(source):
        for timestamp, value in (portfolio.get("cash_curve") or {}).items():
            if isinstance(value, dict):
                rows.extend({
                    "strategy": strategy, "timestamp": timestamp,
                    "currency": str(currency), "cash": amount,
                } for currency, amount in value.items())
            else:
                rows.append({
                    "strategy": strategy, "timestamp": timestamp,
                    "currency": "", "cash": value,
                })
    if rows:
        return rows
    # The retained order audit already owns the authoritative settlement
    # deltas.  Use it when the execution engine does not publish a dense cash
    # curve, avoiding a second replay-time accounting projection.
    for item in fill_rows(source):
        if item.get("cash_before") is None and item.get("cash_after") is None:
            continue
        rows.append({
            "strategy": item.get("strategy"),
            "timestamp": item.get("timestamp"),
            "fill_id": item.get("fill_id"),
            **{
                key: item.get(key) for key in (
                    "account_id", "account_ref", "account", "ledger_id", "ledger",
                    "cash_pool_id", "cash_pool", "pool_id",
                    "account_currency", "ledger_currency", "currency",
                    "cash_pool_base_currency", "pool_base_currency", "base_currency",
                ) if item.get(key) not in (None, "")
            },
            "cash_before": item.get("cash_before"),
            "cash_after": item.get("cash_after"),
            "cash_change": item.get("cash_change"),
        })
    return rows


def position_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, portfolio in _portfolios(source):
        for timestamp, positions in (portfolio.get("position_curve") or {}).items():
            if not isinstance(positions, dict):
                continue
            rows.extend({
                "strategy": strategy, "timestamp": timestamp,
                "product": str(product), "quantity": quantity,
            } for product, quantity in positions.items())
    return rows


def exposure_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, portfolio in _portfolios(source):
        equities = portfolio.get("equity_curve") or portfolio.get("display_equity_curve") or {}
        for timestamp, notionals in (portfolio.get("notional_curve") or {}).items():
            if not isinstance(notionals, dict):
                continue
            values = [_number(value) for value in notionals.values()]
            finite = [value for value in values if value is not None]
            gross = sum(abs(value) for value in finite)
            net = sum(finite)
            equity = _number(equities.get(timestamp))
            rows.append({
                "strategy": strategy, "timestamp": timestamp,
                "gross_exposure": gross, "net_exposure": net,
                "equity": equity,
                "gross_leverage": gross / equity if equity else None,
                "net_leverage": net / equity if equity else None,
            })
    return rows


def turnover_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, portfolio in _portfolios(source):
        turnover = portfolio.get("fill_turnover")
        if isinstance(turnover, dict):
            rows.append({
                "strategy": strategy,
                **{key: value for key, value in turnover.items() if key != "series"},
            })
            rows.extend({
                "strategy": strategy,
                "timestamp": item.get("timestamp"),
                "turnover": item.get("turnover"),
                "source": turnover.get("source"),
            } for item in turnover.get("series") or () if isinstance(item, dict))
    return rows


def _audit_rows(source: dict[str, Any], key: str) -> list[dict[str, Any]]:
    audit = source.get("order_audit") or {}
    strategies = audit.get("strategies") if isinstance(audit, dict) else {}
    return [
        {"strategy": str(strategy), **item}
        for strategy, payload in (strategies or {}).items()
        if isinstance(payload, dict)
        for item in payload.get(key) or ()
        if isinstance(item, dict)
    ]


def _portfolios(source: dict[str, Any]):
    for strategy, portfolio in (engine_result(source).get("portfolios") or {}).items():
        if isinstance(portfolio, dict):
            yield str(strategy), portfolio


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
