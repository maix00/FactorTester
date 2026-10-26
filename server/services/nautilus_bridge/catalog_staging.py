"""Stage frozen RunSpec products into receipt-checked Nautilus catalogs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from server.services.nautilus_bridge.catalog import stage_contract_minute_catalog
from server.services.nautilus_bridge.market_data import FuturesContractSpec, iter_minute_bars
from server.modules.shared.price_services import (
    cn_futures_trading_spec_fields,
    contract_data_path_for,
    find_contract_product,
)
from server.services.nautilus_bridge.source_registry import from_server_sources


def _ns(value: str) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1_000_000_000)


def build_contract_spec(
    contract_uid: str, *, product: Any, contract_row: dict[str, Any],
    spec_fields: dict[str, Any], source_key: str, frequency: str,
) -> FuturesContractSpec:
    parts = str(contract_uid).split("|")
    if len(parts) != 4 or parts[1] != "F":
        raise ValueError(f"unsupported contract UID: {contract_uid}")
    venue, underlying, month = parts[0], parts[2], parts[3]
    min_tick = Decimal(str(spec_fields["min_tick"]))
    precision = max(0, -min_tick.as_tuple().exponent)
    margin = max(
        Decimal(str(spec_fields.get("long_margin_ratio") or 0)),
        Decimal(str(spec_fields.get("short_margin_ratio") or 0)),
    )
    resolved_source = from_server_sources().resolve(
        source_key, frequency=frequency, product=product,
    )
    start_ns = int(contract_row["start_ts"]) * 1_000_000
    end_ns = (int(contract_row["end_ts"]) + 86_400_000) * 1_000_000 - 1
    return FuturesContractSpec(
        instrument_code=f"{underlying}{month}".lower(), venue=venue,
        underlying=underlying.lower(),
        price_increment=min_tick, price_precision=precision,
        multiplier=Decimal(str(spec_fields["point_value"])), currency="CNY",
        activation_ns=start_ns, expiration_ns=end_ns,
        margin_init=margin, margin_maint=margin,
        provenance=str(spec_fields.get("trading_spec_source") or "run_spec_product_catalog"),
        resolved_source=resolved_source,
    )


def build_run_spec_session_calendar(
    *, staging_requests: list[dict[str, Any]], source_key: str,
    frequency: str, start_utc: str, end_utc: str,
) -> Any:
    """Build the authoritative TradeResearch session window from source bars."""
    from tools.factors.expr.streaming.calendar_window import TradingCalendarWindow

    start_ns, end_ns = _ns(start_utc), _ns(end_utc)
    bars = []
    for request in staging_requests:
        for contract_uid in request["paths"]:
            product = find_contract_product(contract_uid)
            if product is None:
                raise ValueError(f"contract is not in the product catalog: {contract_uid}")
            path = contract_data_path_for(contract_uid, product)
            bars.extend(
                bar for bar in iter_minute_bars(
                    path, start_ns=start_ns, end_ns=end_ns,
                )
                if hasattr(bar, "trading_day")
            )
    if not bars:
        raise ValueError("source bars produced an empty trading calendar")
    return TradingCalendarWindow.from_contract_bars(bars)


def stage_run_spec_catalogs(
    *, staging_requests: list[dict[str, Any]], source_key: str, frequency: str,
    start_utc: str, end_utc: str, target_root: Path,
) -> dict[str, dict[str, str]]:
    start_ns, end_ns = _ns(start_utc), _ns(end_utc)
    target_root.mkdir(parents=True, exist_ok=True)
    catalogs: dict[str, dict[str, str]] = {}
    for request in staging_requests:
        for contract_uid in request["paths"]:
            product = find_contract_product(contract_uid)
            if product is None:
                raise ValueError(f"contract is not in the product catalog: {contract_uid}")
            parent = product.get_parent_product()
            rows = parent.get_contract_list(start_utc[:10], end_utc[:10]) if parent else []
            row = next((item for item in rows if str(item.get("uid")) == contract_uid), None)
            if row is None:
                raise ValueError(f"contract has no frozen lifecycle row: {contract_uid}")
            fields = cn_futures_trading_spec_fields(product)
            if not fields or fields.get("point_value") is None or fields.get("min_tick") is None:
                raise ValueError(f"contract has no trading specification: {contract_uid}")
            spec = build_contract_spec(
                contract_uid, product=product, contract_row=row,
                spec_fields=fields, source_key=source_key, frequency=frequency,
            )
            target = target_root / str(contract_uid).replace("|", "_")
            stage_contract_minute_catalog(
                contract_data_path_for(contract_uid, product), target,
                contract_uid=contract_uid, instrument_spec=spec,
                start_ns=max(start_ns, spec.activation_ns),
                end_ns=min(end_ns, spec.expiration_ns),
            )
            product_key = str(contract_uid).split("|")[2]
            catalogs.setdefault(product_key, {
                "catalog_dir": str(target), "contract_uid": str(contract_uid),
            })
    return catalogs
