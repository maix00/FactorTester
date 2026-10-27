"""Source-owned Chinese futures lifecycle, specification and catalog loading.

Activated explicitly through the installed Bundle manifest. No platform
selector needs to know this source's UID syntax or physical data paths.
"""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from server.services.nautilus_bridge.catalog import (
    stage_contract_daily_catalog, stage_contract_minute_catalog,
)
from traderesearch_data.nautilus import CatalogLoadRequest
from server.services.nautilus_bridge.market_data import FuturesContractSpec
from server.modules.shared.price_services import (
    cn_futures_trading_spec_fields, contract_data_path_for, find_contract_product,
)
from server.services.nautilus_bridge.source_registry import from_server_sources


def _finite_decimal(value: Any, name: str, contract_uid: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{contract_uid}: {name} is not numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{contract_uid}: {name} must be finite")
    return number


def build_contract_spec(
    contract_uid: str, *, product: Any, contract_row: dict[str, Any],
    spec_fields: dict[str, Any], source_key: str, frequency: str,
) -> FuturesContractSpec:
    parts = str(contract_uid).split("|")
    if len(parts) != 4 or parts[1] != "F":
        raise ValueError(f"unsupported contract UID: {contract_uid}")
    venue, underlying, month = parts[0], parts[2], parts[3]
    min_tick = _finite_decimal(spec_fields["min_tick"], "min_tick", contract_uid)
    multiplier = _finite_decimal(spec_fields["point_value"], "point_value", contract_uid)
    if min_tick <= 0 or multiplier <= 0:
        raise ValueError(f"{contract_uid}: tick and multiplier must be positive")
    precision = max(0, -min_tick.as_tuple().exponent)

    long_raw = spec_fields.get("long_margin_ratio")
    short_raw = spec_fields.get("short_margin_ratio")
    if long_raw is None or short_raw is None:
        raise ValueError(f"contract has no side-specific margin: {contract_uid}")
    long_margin = _finite_decimal(long_raw, "long_margin_ratio", contract_uid)
    short_margin = _finite_decimal(short_raw, "short_margin_ratio", contract_uid)
    if long_margin != short_margin:
        raise ValueError(
            f"{contract_uid}: side-specific margin is not representable by the "
            "current single-margin Instrument contract"
        )
    initial_margin = spec_fields.get("initial_margin_ratio")
    maintenance_margin = spec_fields.get("maintenance_margin_ratio")
    if initial_margin is None:
        raise ValueError(f"{contract_uid}: missing initial_margin_ratio")
    if maintenance_margin is None:
        raise ValueError(f"{contract_uid}: missing maintenance_margin_ratio")
    initial_margin = _finite_decimal(
        initial_margin, "initial_margin_ratio", contract_uid,
    )
    maintenance_margin = _finite_decimal(
        maintenance_margin, "maintenance_margin_ratio", contract_uid,
    )
    if initial_margin < 0 or maintenance_margin < 0:
        raise ValueError(f"{contract_uid}: margin ratios must be non-negative")

    resolved_source = from_server_sources().resolve(
        source_key, frequency=frequency, product=product,
    )
    start_ns = int(contract_row["start_ts"]) * 1_000_000
    end_ns = (int(contract_row["end_ts"]) + 86_400_000) * 1_000_000 - 1
    return FuturesContractSpec(
        instrument_code=f"{underlying}{month}", venue=venue,
        underlying=underlying,
        price_increment=min_tick, price_precision=precision,
        multiplier=multiplier, currency="CNY",
        activation_ns=start_ns, expiration_ns=end_ns,
        margin_init=initial_margin, margin_maint=maintenance_margin,
        provenance=str(spec_fields.get("trading_spec_source") or "run_spec_product_catalog"),
        resolved_source=resolved_source,
    )

_SESSION_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def _trading_day_map(path: str) -> dict[Any, Any]:
    """Read the source's trading-day labels once and map each to its predecessor."""
    try:
        import pyarrow.dataset as ds
        table = ds.dataset(path, format="parquet").to_table(columns=["TRADING_DAY"])
        values = sorted({
            value.date() if isinstance(value, datetime) else value
            for value in table.column("TRADING_DAY").to_pylist()
            if value is not None
        })
    except Exception:
        return {}
    return dict(zip(values[1:], values[:-1]))


def _session_for_day(product: Any, previous_days: dict[Any, Any] | None = None):
    """Resolve day-session bounds and, when available, the preceding night open."""
    text = str(getattr(product, "trading_day_sessions", "") or "")
    intervals = _SESSION_RE.findall(text)
    if not intervals:
        raise ValueError("DAY1 source product has no trading session schedule")
    start_hour, start_minute = (int(value) for value in intervals[0][:2])
    close_text = str(getattr(product, "trading_day_close_time", "") or "")
    close_match = re.fullmatch(r"(\d{1,2}):(\d{2})", close_text)
    if close_match:
        close_hour, close_minute = (int(value) for value in close_match.groups())
    else:
        close_hour, close_minute = (int(value) for value in intervals[-1][2:])
    night = _SESSION_RE.findall(str(getattr(product, "night_session", "") or ""))
    previous_days = previous_days or {}
    timezone = ZoneInfo("Asia/Shanghai")

    def session(day):
        open_day, open_hour, open_minute = day, start_hour, start_minute
        if night:
            night_hour, night_minute = (int(value) for value in night[0][:2])
            previous = previous_days.get(day)
            if previous is not None:
                open_day, open_hour, open_minute = previous, night_hour, night_minute
        return (
            datetime.combine(open_day, time(open_hour, open_minute), tzinfo=timezone),
            datetime.combine(day, time(close_hour, close_minute), tzinfo=timezone),
        )

    return session


def stage_catalogs(request: CatalogLoadRequest) -> dict[str, dict[str, str]]:
    frequency = request.frequency
    source_key = request.source_key
    start_utc, end_utc = request.start_utc, request.end_utc
    start_ns, end_ns = request.start_ns, request.end_ns
    target_root = request.target_root
    staging_requests = request.staging_requests
    bundle_identity = dict(
        bundle_id=request.bundle_id, bundle_version=request.bundle_version,
        bundle_fingerprint=request.bundle_fingerprint, member_id=request.member_id,
    )
    if frequency not in {"MIN1", "DAY1"}:
        raise ValueError(f"{frequency}: unsupported source-owned catalog frequency")
    if "FieldHistory:market_rules:exchange" not in request.related_members:
        raise ValueError(
            "LocalCNFutures market member does not declare its historical rules member"
        )
    product_contracts: dict[str, str] = {}
    for request in staging_requests:
        for contract_uid in request.paths:
            product_key = str(contract_uid).split("|")[2]
            previous = product_contracts.get(product_key)
            if previous is not None and previous != str(contract_uid):
                raise ValueError(
                    f"{product_key}: multiple contracts are not supported by the "
                    "single-catalog consumer contract"
                )
            product_contracts[product_key] = str(contract_uid)
    target_root.mkdir(parents=True, exist_ok=True)
    catalogs: dict[str, dict[str, str]] = {}
    seen_contracts: set[str] = set()
    for request in staging_requests:
        for contract_uid in request.paths:
            if contract_uid in seen_contracts:
                continue
            seen_contracts.add(contract_uid)
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
            clipped_start = max(start_ns, spec.activation_ns)
            clipped_end = min(end_ns, spec.expiration_ns)
            if frequency == "MIN1":
                stage_contract_minute_catalog(
                    contract_data_path_for(contract_uid, product), target,
                    contract_uid=contract_uid, instrument_spec=spec,
                    start_ns=clipped_start, end_ns=clipped_end,
                    **bundle_identity,
                )
            else:
                if parent is None:
                    raise ValueError(f"contract has no parent product: {contract_uid}")
                term_path = parent.get_term_structure_path()
                if not term_path:
                    raise ValueError(f"product has no DAY1 term-structure artifact: {contract_uid}")
                codes = tuple(str(value) for value in (
                    parent.name, getattr(parent, "alias", None),
                ) if value)
                stage_contract_daily_catalog(
                    term_path, target, contract_uid=contract_uid,
                    instrument_spec=spec, start_ns=clipped_start, end_ns=clipped_end,
                    product_codes=set(codes),
                    session_for_day=_session_for_day(
                        parent, _trading_day_map(term_path),
                    ),
                    **bundle_identity,
                )
            product_key = str(contract_uid).split("|")[2]
            catalogs[product_key] = {
                "catalog_dir": str(target), "contract_uid": str(contract_uid),
            }
    return catalogs
