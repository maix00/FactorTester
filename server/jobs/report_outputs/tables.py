"""Fee, margin, and ratio table projections."""

from __future__ import annotations

from typing import Any

from .series import finite_number


def fee_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    audit = source.get("order_audit") or {}
    strategies = audit.get("strategies") if isinstance(audit, dict) else {}
    rows = []
    for strategy, payload in (strategies or {}).items():
        if not isinstance(payload, dict):
            continue
        fills = [item for item in payload.get("fills") or () if isinstance(item, dict)]
        fill_ids = {str(item.get("fill_id")) for item in fills if item.get("fill_id")}
        events = [("fills", index, item) for index, item in enumerate(fills)]
        # Native accounting records the same fee on Fill and FillSettlement.
        # Settlement-only rows remain a compatibility source, but a paired
        # settlement must not double count the authoritative fill fee.
        events.extend(
            ("settlements", index, item)
            for index, item in enumerate(payload.get("settlements") or ())
            if isinstance(item, dict)
            and (not item.get("fill_id") or str(item.get("fill_id")) not in fill_ids)
        )
        for kind, index, item in events:
            rows.append({
                "strategy": strategy, "event_type": kind, "row": index,
                "fill_id": item.get("fill_id"),
                "timestamp": item.get("timestamp"),
                "product": item.get("instrument", item.get("product")),
                "side": item.get("side"), "offset": item.get("offset"),
                "fee": item.get("fee", item.get("fees", item.get("fee_amount", 0.0))),
                "raw": item,
            })
    return rows


def margin_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    engine = source.get("engine_result") or {}
    rows = []
    for strategy, portfolio in (engine.get("portfolios") or {}).items():
        if not isinstance(portfolio, dict):
            continue
        margins = portfolio.get("margin_curve") or {}
        notionals = portfolio.get("notional_curve") or {}
        equities = portfolio.get("equity_curve") or portfolio.get("display_equity_curve") or {}
        for timestamp, margin in margins.items():
            equity = float(equities.get(timestamp, 0.0) or 0.0)
            if isinstance(margin, dict):
                for product, value in margin.items():
                    notional = (notionals.get(timestamp) or {}).get(product, 0.0)
                    rows.append(_margin_row(strategy, timestamp, product, value, notional, equity))
            else:
                notional = sum((notionals.get(timestamp) or {}).values()) if isinstance(notionals.get(timestamp), dict) else None
                rows.append(_margin_row(strategy, timestamp, "__total__", margin, notional, equity))
    return rows


def _margin_row(strategy, timestamp, product, margin, notional, equity):
    return {"strategy": strategy, "timestamp": timestamp, "product": product, "margin": margin,
            "notional": notional, "equity": equity,
            "margin_utilization": float(margin or 0.0) / equity if equity else None}


def ratio_rows(
    result: dict[str, Any], source: dict[str, Any], series: list[dict[str, Any]],
    *, fee_rows_value: list[dict[str, Any]] | None = None,
    margin_rows_value: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    metrics = result.get("metrics") or {}
    if isinstance(metrics, dict):
        rows.extend({"series": name, **values} for name, values in metrics.items() if isinstance(values, dict))
    fee_total = sum(finite_number(item.get("fee")) for item in (
        fee_rows_value if fee_rows_value is not None else fee_rows(source)
    ))
    margin_total = sum(finite_number(item.get("margin")) for item in (
        margin_rows_value if margin_rows_value is not None else margin_rows(source)
    ))
    gross = sum(item["values"][-1] - item["values"][0] for item in series)
    rows.append({"series": "__aggregate__", "gross_change": gross, "fee_total": fee_total,
                 "gross_to_fee_ratio": gross / fee_total if fee_total else None,
                 "margin_observation_sum": margin_total})
    return rows
