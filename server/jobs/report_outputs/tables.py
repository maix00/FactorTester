"""Fee, margin, ratio, and generic table report projections."""

from __future__ import annotations

from typing import Any

from .models import GeneratedReport
from .render import csv_bytes, json_bytes
from .series import finite_number


def fee_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    audit = source.get("order_audit") or {}
    strategies = audit.get("strategies") if isinstance(audit, dict) else {}
    rows = []
    for strategy, payload in (strategies or {}).items():
        if not isinstance(payload, dict):
            continue
        fills = [item for item in payload.get("fills") or () if isinstance(item, dict)]
        settlements = {
            str(item.get("fill_id")): item
            for item in payload.get("settlements") or ()
            if isinstance(item, dict) and item.get("fill_id")
        }
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
            settlement = settlements.get(str(item.get("fill_id") or ""), {})
            rows.append({
                "strategy": strategy, "event_type": kind, "row": index,
                "fill_id": item.get("fill_id"),
                "timestamp": item.get("timestamp"),
                "product": item.get("instrument", item.get("product")),
                "side": item.get("side"), "offset": item.get("offset"),
                **{
                    key: settlement.get(key, item.get(key)) for key in (
                        "account_id", "account_ref", "account", "ledger_id", "ledger",
                        "cash_pool_id", "cash_pool", "pool_id",
                        "account_currency", "ledger_currency", "currency",
                        "cash_pool_base_currency", "pool_base_currency", "base_currency",
                    ) if settlement.get(key, item.get(key)) not in (None, "")
                },
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


def table_reports(name, rows, *, payload_extra=None, columns=None):
    """Create the canonical CSV/JSON pair for a paginated report table."""

    declared_columns = list(columns) if columns is not None else list(dict.fromkeys(
        key for row in rows for key in row if key != "raw"
    ))
    column_presentations = {}
    if any(row.get("factor_alias") and row.get("factor_ref") for row in rows):
        column_presentations["factor_alias"] = {
            "presentation": "reference",
            "kind": "factor",
            "target_ref_field": "factor_ref",
        }
    receipt = {
        "schema_version": 1,
        "artifact_kind": name,
        "row_count": len(rows),
        "columns": declared_columns,
        "column_presentations": column_presentations,
    }
    json_columns = declared_columns or ["value"]
    payload = {
        "schema_version": 1,
        "artifact_kind": name,
        "columns": json_columns,
        "column_presentations": column_presentations,
        "rows": rows,
    }
    if isinstance(payload_extra, dict):
        payload.update(payload_extra)
        for key in ("artifact_role", "source_artifacts", "link_columns", "aggregation"):
            if key in payload_extra:
                receipt[key] = payload_extra[key]
    return [
        GeneratedReport(
            f"{name}_csv", csv_bytes(rows, columns=declared_columns),
            "csv", "text/csv; charset=utf-8", receipt,
        ),
        GeneratedReport(
            f"{name}_data", json_bytes(payload),
            "json", "application/json", receipt,
        ),
    ]


__all__ = ["fee_rows", "margin_rows", "ratio_rows", "table_reports"]
