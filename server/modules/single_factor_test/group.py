"""Group test endpoint."""
import hashlib
import json
import uuid
import logging, math, time, traceback
from copy import deepcopy
from typing import Any, cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.data.field_history import load_market_rule_field_provider
from tools.data.types import DataColumn
from tools.data.types.currency import normalize_currency, require_product_currency_vector
from tools.data.types.currency_units import minor_units_to_major
from tools.data.types.time_index import DataIndex
from tools.factors.FactorTester import FactorTester, _active_tester, _signal_time
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.testers.backtest.modules.market_data import historical_field_frames_for_market_data


def infer_periods_per_year(index_like) -> float:
    """Infer strategy periods/year from realised signal timestamps."""
    idx = DataIndex(pd.Index(index_like)).signal_index
    idx = idx.dropna()
    if len(idx) < 2:
        return 252.0
    per_day = pd.Series(1, index=idx.normalize()).groupby(level=0).sum()
    median_per_day = float(per_day.median()) if not per_day.empty else 1.0
    if median_per_day > 1:
        return median_per_day * 252.0
    unique_days = pd.DatetimeIndex(per_day.index).sort_values()
    if len(unique_days) < 2:
        return 252.0
    business_days = np.busday_count(
        unique_days[0].date().isoformat(),
        (unique_days[-1] + pd.Timedelta(days=1)).date().isoformat(),
    )
    if business_days <= 0:
        return 252.0
    return max(1.0, len(unique_days) / business_days * 252.0)


def _core_emit_progress(*args, **kwargs):  # noqa: ANN001 — issue-114 stub
    raise NotImplementedError(
        "_emit_progress: pending issue-114 step 11 production rewiring")


def ensure_group_factor_inputs(*args, **kwargs):  # noqa: ANN001 — issue-114 stub
    raise NotImplementedError(
        "ensure_group_factor_inputs: pending issue-114 step 11 production rewiring")
from tools.factors.tester_calc.single_factor_test.group.detail import (
    build_group_detail,
    _build_product_fee_rates,
    _display_with_fee as _display_product_with_fee,
)
from tools.factors.tester_calc.single_factor_test.group.metadata import GROUP_TEST_PHASES, GROUP_TEST_METRICS_META
from tools.factors.tester_calc.single_factor_test.group.monotonicity import build_group_ranking_detail
from tools.factors.tester_calc.single_factor_test.group.research_run import (
    execute_group_run_spec,
    prepare_group_run_spec,
)
from tools.factors.tester_calc.single_factor_test.group.research_run.projection import (
    serialize_event_execution as _serialize_event_execution,
)
from tools.factors.tester_calc.single_factor_test.group.research_run.settings import (
    build_group_owner_rows as _build_group_owner_rows,
    build_long_short_owner_rows as _build_long_short_owner_rows,
    long_short_strategy_id as _long_short_strategy_id,
    resolve_flat_backtest_settings as _resolve_flat_backtest_settings,
    resolve_group_strategy_settings as _resolve_group_strategy_settings,
    resolve_long_short_strategy_settings as _resolve_long_short_strategy_settings,
    resolve_run_datetimes as _resolve_run_datetimes,
    runtime_datetimes as _runtime_datetimes,
    silent_default_settings_for_run as _silent_default_settings_for_run,
)
from tools.products.AdjustableTermStructure import resolve_term_structure_product
from tools.products.Product import Product
from tools.products.product_utils import product_display_name
from tools.testers.settings import backtest_setting_registry
from tools.testers.settings.resolver import resolve_group_settings
from tools.testers.backtest.modules.registry import GroupTestModuleRegistry
from . import sft_bp
import server.services.page_runtime as runtime_state
from server.services.session_runtime import current_user, current_user_obj
from server.modules.shared.price_data_helpers import to_epoch_ms

from server.modules.shared.factor_tester_runtime import create_factor_tester_for_product_path_selection

_log = logging.getLogger(__name__)


_GROUP_INHERIT_UNIQUE_KEYS = {"id", "name", "parentId", "_expanded"}
# Silent default keys now come from the registry — no hardcoded constant list


def _load_raw_market_data_for(products: list[Any], start_dt: Any, end_dt: Any) -> dict[str, Any]:
    """Compatibility facade for old group endpoint tests.

    Production backtest loading is owned by MarketDataModule.  A few server
    tests and old diagnostic scripts still call this group-level helper to
    assert coverage behavior, so keep a narrow facade with the same observable
    contract instead of reintroducing the old execution path.
    """
    series_by_product: dict[Any, pd.Series] = {}
    missing_products: list[str] = []
    excluded_out_of_range: list[Any] = []
    for product in products:
        try:
            available_freqs = list(product.list_available_freqs())
            if not available_freqs:
                if _product_outside_run_window(product, start_dt, end_dt):
                    excluded_out_of_range.append(product)
                else:
                    missing_products.append(str(getattr(product, "name", product)))
                continue
            current_freq = getattr(product, "current_freq", None)
            freq = cast(Any, current_freq if current_freq in available_freqs else available_freqs[0])
            data_view = getattr(product, freq.name)
            df = data_view.get_and_adjust_cols([DataColumn.CLOSE.name], copy=False, start_dt=start_dt, end_dt=end_dt)
        except (ValueError, KeyError, AttributeError):
            if _product_outside_run_window(product, start_dt, end_dt):
                excluded_out_of_range.append(product)
            else:
                missing_products.append(str(getattr(product, "name", product)))
            continue
        if df.empty or DataColumn.CLOSE.name not in df.columns:
            if _product_outside_run_window(product, start_dt, end_dt):
                excluded_out_of_range.append(product)
            else:
                missing_products.append(str(getattr(product, "name", product)))
            continue
        series_by_product[product] = df[DataColumn.CLOSE.name]
    if missing_products:
        sample = ", ".join(sorted(set(missing_products))[:20])
        raise ValueError(
            "回测产品池存在本地行情缺口，不能静默跳过或按 0 估值："
            f"{sample}；窗口={getattr(start_dt, 'ts', start_dt)} 到 {getattr(end_dt, 'ts', end_dt)}。"
            "请检查产品路径是否包含已退市/无分钟数据品种，或先补齐对应行情数据。"
        )
    raw_prices = pd.DataFrame(series_by_product) if series_by_product else pd.DataFrame()
    provider = load_market_rule_field_provider()
    historical_frames = historical_field_frames_for_market_data(
        list(raw_prices.columns),
        raw_prices.index,
        provider=provider,
        trading_day_resolver=None,
        field_names=(),
        policy="latest_available",
    )
    return {
        "raw_prices": raw_prices,
        "historical_field_provider": provider,
        "historical_field_frames": historical_frames,
        "included_products": tuple(series_by_product.keys()),
        "excluded_out_of_range_products": tuple(str(getattr(product, "name", product)) for product in _dedupe_products(excluded_out_of_range)),
    }


def _dedupe_products(products: list[Any]) -> list[Any]:
    result: list[Any] = []
    for product in products:
        if product not in result:
            result.append(product)
    return result


def _supports_local_cnfutures_coverage(_product: Any) -> bool:
    return False


def _product_outside_run_window(product: Any, start_dt: Any, end_dt: Any) -> bool:
    if not _supports_local_cnfutures_coverage(product):
        return False
    coverage = _product_data_coverage(product)
    if coverage is None:
        return False
    data_start, data_end = coverage
    start_key = _datetime_sort_key(getattr(start_dt, "sort_key", lambda: None)())
    end_key = _datetime_sort_key(getattr(end_dt, "sort_key", lambda: None)())
    if start_key is not None and data_end is not None and data_end < start_key:
        return True
    if end_key is not None and data_start is not None and data_start > end_key:
        return True
    return False


def _product_data_coverage(product: Any) -> tuple[pd.Timestamp | None, pd.Timestamp | None] | None:
    try:
        available_freqs = list(product.list_available_freqs())
    except Exception:
        available_freqs = []
    for freq in available_freqs:
        try:
            view = getattr(product, freq.name)
            data = view.get_data(copy=False)
        except Exception:
            continue
        if data is None or data.empty:
            continue
        index = DataIndex(data.index).signal_index
        if len(index) == 0:
            continue
        return _datetime_sort_key(index.min()), _datetime_sort_key(index.max())
    return None


def _datetime_sort_key(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp


def _group_product_path_selection_id(group: dict[str, Any]) -> str:
    selection = group.get("product_path_selection")
    if isinstance(selection, dict):
        selection_id = str(
            selection.get("product_path_selection_id")
            or selection.get("selection_id")
            or selection.get("id")
            or ""
        )
        if selection_id:
            return selection_id
    return str(group.get("product_path_selection_id") or "")


def _groups_with_parent_fallback(groups: list[dict]) -> list[dict]:
    """Build derived-group views without mutating their parent or identity."""
    groups_by_id = {
        str(group.get("id")): group
        for group in groups
        if isinstance(group, dict) and group.get("id")
    }
    resolving: set[str] = set()
    resolved: dict[str, dict] = {}

    def resolve(group: dict) -> dict:
        group_id = str(group.get("id") or "")
        if group_id and group_id in resolved:
            return deepcopy(resolved[group_id])
        if group_id:
            if group_id in resolving:
                return deepcopy(group)
            resolving.add(group_id)
        merged = deepcopy(group)
        parent = groups_by_id.get(str(group.get("parentId") or ""))
        if isinstance(parent, dict):
            parent_view = resolve(parent)
            for key, value in parent_view.items():
                if key in _GROUP_INHERIT_UNIQUE_KEYS:
                    continue
                if merged.get(key) in (None, ""):
                    merged[key] = deepcopy(value)
        if group_id:
            resolving.discard(group_id)
            resolved[group_id] = deepcopy(merged)
        return merged

    return [resolve(group) if isinstance(group, dict) else group for group in groups]


def _ensure_tester_factors_for_group(
    tester: Any,
    factor_aliases: list[str],
    factor_family_alias: str | None,
    *,
    username: str | None = None,
    page_uuid: str | None = None,
) -> None:
    """Ensure direct group runs can resolve factors from page_factors.

    Factors are the single source of truth — no session-scoped params dict.
    When page_uuid is provided, factors are looked up from page_factors directly.
    When page_uuid is absent, factors must already be on the tester (caller error).
    """
    missing_aliases = [
        str(alias) for alias in factor_aliases
        if alias and tester.resolve_factor(str(alias)) is None
    ]
    if not missing_aliases:
        return

    if not page_uuid:
        return

    from server.services.factor_registry import page_factors
    page_dict = page_factors.get(str(page_uuid), {})

    existing_by_alias = {getattr(f, 'alias', ''): i for i, f in enumerate(getattr(tester, 'factors', []))}
    for alias in missing_aliases:
        factor = page_dict.get(alias)
        if factor is None:
            continue
        if alias in existing_by_alias:
            tester.factors[existing_by_alias[alias]] = factor
        else:
            tester.factors.append(factor)
            existing_by_alias[alias] = len(tester.factors) - 1


def _progress(message: str) -> None:
    print(f"[GroupTest] {message}", flush=True)


# ── Module registry singleton ──────────────────────────────────

_group_test_registry: GroupTestModuleRegistry | None = None


def _get_group_test_registry() -> GroupTestModuleRegistry:
    """Return the cached GroupTestModuleRegistry singleton."""
    global _group_test_registry
    if _group_test_registry is None:
        _group_test_registry = GroupTestModuleRegistry()
    return _group_test_registry


def _get_metrics_meta() -> dict:
    """Return the single-source metrics metadata for frontend rendering."""
    return GROUP_TEST_METRICS_META


def _safe_float(v):
    """安全转为 float，NaN/inf 返回 None。"""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


def _safe_bool(obj) -> bool:
    """安全求布尔值，避免 numpy 数组的 ambiguous truth value 错误。"""
    if obj is None:
        return False
    if isinstance(obj, np.ndarray):
        return bool(obj.size > 0)
    return bool(obj)


def _group_has_signal_window_override(group: dict[str, Any]) -> bool:
    return any(
        key in group and group.get(key) not in (None, "")
        for key in ("start_date", "end_date", "start_time", "end_time", "time_precision", "timezone")
    )


def _parse_group_fee_config(data: dict) -> tuple[float, list, bool]:
    """Parse legacy group-test fee payload into engine inputs.

    ``fee`` is provided in percent units by the UI, while the engine expects a
    ratio. Per-variety modifications are cleaned into FeeModification objects.
    """
    from tools.products.transactions.fees import clean_modifications

    raw_fee = data.get('fee', 0)
    fee_value = _safe_float(raw_fee)
    fee_uniform = 0.0 if fee_value is None else float(fee_value) / 100.0
    raw_modifications = data.get('fee_modifications') or data.get('feeModifications') or []
    if not isinstance(raw_modifications, list):
        raw_modifications = []
    fee_modifications = clean_modifications(raw_modifications)
    use_closetoday = bool(data.get('use_closetoday') or data.get('useCloseToday'))
    return fee_uniform, fee_modifications, use_closetoday


def _product_fee_rates_by_name(group_result: Any) -> dict[str, dict[str, float]]:
    """Build per-product fee rows from a group result."""
    if group_result is None:
        return {}
    return _build_product_fee_rates(
        getattr(group_result, 'valid_cols', None),
        getattr(group_result, 'open_ratio_mat', None),
        getattr(group_result, 'close_ratio_mat', None),
        getattr(group_result, 'close_today_ratio_mat', None),
    )


def _registered_product(product_name: str):
    if not product_name:
        return None
    product = resolve_term_structure_product(product_name)
    if product is not None:
        return product
    try:
        from sources.LocalCNFutures.CNFutures import CNFutures
        if "." in str(product_name):
            return CNFutures(str(product_name))
    except Exception:
        return None
    return None


def _cn_futures_desc_from_openctp(product_name: Any) -> str | None:
    name = str(product_name or "").strip()
    if not name:
        return None
    code, exchange = (name.split(".", 1) + [""])[:2] if "." in name else (name, "")
    exchange_map = {
        "CFE": "CFFEX",
        "CZC": "CZCE",
        "GFE": "GFEX",
        "SHF": "SHFE",
    }
    wanted_exchange = exchange_map.get(exchange.upper(), exchange.upper())
    try:
        from sources.OpenCTP.products import load_products_list
    except Exception:
        return None
    try:
        products = load_products_list()
    except Exception:
        return None
    for row in products:
        row_code = str(row.get("ProductID") or "").upper()
        row_exchange = str(row.get("ExchangeID") or "").upper()
        if row_code == code.upper() and (not wanted_exchange or row_exchange == wanted_exchange):
            desc = str(row.get("ProductName") or "").strip()
            return desc or None
    return None


def _cn_futures_catalog_desc(product_name: Any) -> str | None:
    name = str(product_name or "").strip()
    if not name:
        return None
    try:
        from sources.LocalCNFutures.product_catalog import load_product_catalog
    except Exception:
        return _cn_futures_desc_from_openctp(name)
    try:
        catalog = load_product_catalog(sync=False)
    except Exception:
        return _cn_futures_desc_from_openctp(name)
    if catalog is None or getattr(catalog, "empty", True) or "_product_name" not in catalog:
        return _cn_futures_desc_from_openctp(name)
    row = catalog[catalog["_product_name"].astype(str) == name]
    if row.empty and "." in name:
        code, exchange = name.split(".", 1)
        exchange_map = {
            "CFE": "CFFEX",
            "CZC": "CZCE",
            "GFE": "GFEX",
            "SHF": "SHFE",
        }
        code_series = catalog["品种代码"] if "品种代码" in catalog else pd.Series(dtype=object)
        exchange_series = catalog["交易所代码"] if "交易所代码" in catalog else pd.Series(dtype=object)
        row = catalog[
            (code_series.astype(str).str.upper() == code.upper())
            & (
                exchange_series.astype(str)
                .str.upper()
                .isin({exchange.upper(), exchange_map.get(exchange.upper(), exchange.upper())})
            )
        ]
    if row.empty:
        return _cn_futures_desc_from_openctp(name)
    record = row.iloc[0]
    for column in ("合约标的", "简称", "类别"):
        value = record.get(column)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    openctp_desc = _cn_futures_desc_from_openctp(name)
    if openctp_desc:
        return openctp_desc
    code = record.get("品种代码")
    exchange = record.get("交易所代码")
    parts = [
        str(value).strip()
        for value in (code, exchange)
        if value is not None and not pd.isna(value) and str(value).strip()
    ]
    return " · ".join(parts) if parts else None


def _snapshot_product_display(product_ref: Any, fee_rates: dict[str, dict[str, float]] | None = None, *, collapsed_from: str | None = None) -> dict[str, Any]:
    fee_rates = fee_rates or {}
    raw_name = getattr(product_ref, 'name', str(product_ref) if product_ref is not None else '')
    product = product_ref if isinstance(product_ref, Product) else _registered_product(raw_name) if product_ref else None
    if product is not None:
        display = product_display_name(product)
        fee_display = _display_product_with_fee(product, fee_rates)
        fee_value = fee_display.get('fee')
        if fee_value:
            display['fee'] = str(fee_value)
    else:
        display = _display_product_with_fee(raw_name, fee_rates)
    name = display.get('name') or raw_name
    if display.get('desc') in (None, '', name):
        desc = _cn_futures_catalog_desc(name or raw_name)
        if desc and desc != name:
            display['desc'] = desc
    if collapsed_from and collapsed_from != name:
        display['source_name'] = collapsed_from
    return display


def _cn_futures_contract_parent(product_ref: Any):
    contract_uid = getattr(product_ref, 'name', None) or str(product_ref)
    if not contract_uid:
        return None
    try:
        from sources.LocalCNFutures.CNFutures import CNFutures
        return CNFutures.get_contract_parent(str(contract_uid))
    except Exception:
        return None


def _product_parent_name(product_ref: Any) -> str:
    raw = str(product_ref or "")
    parts = raw.split("|")
    if len(parts) >= 4:
        exchange, _, code = parts[:3]
        return f"{code}.{exchange}"
    parent = _cn_futures_contract_parent(product_ref)
    if parent is not None:
        return str(getattr(parent, "name", parent))
    name = raw
    if "@" in name:
        return name.split("@", 1)[0]
    return name


def _event_instrument_display(instrument: str, *, collapse_product: bool = False) -> dict[str, Any]:
    if collapse_product:
        display_ref = _product_parent_name(instrument)
        display = _snapshot_product_display(display_ref)
        if display_ref != instrument:
            display["source_name"] = instrument
        return display
    parts = str(instrument or "").split("|")
    if len(parts) >= 4:
        exchange, _, code, delivery = parts[:4]
        parent_name = _product_parent_name(instrument)
        parent_display = _snapshot_product_display(parent_name)
        return {
            "name": f"{code}{delivery}.{exchange}",
            "desc": parent_display.get("desc") or parent_display.get("name") or parent_name,
            "source_name": instrument,
        }
    display = _snapshot_product_display(instrument)
    return display


def _first_finite(values: list[Any], default: float | None = None) -> float | None:
    for value in values:
        try:
            number = float(value)
        except Exception:
            continue
        if math.isfinite(number):
            return number
    return default


def _event_market_rule_rows(payload: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    instruments = list(payload.get("instruments") or [])
    rules = payload.get("market_rules") or {}
    multipliers = rules.get("multipliers") or []
    lot_sizes = rules.get("lot_sizes") or []
    margin_ratios = rules.get("margin_ratios") or []
    rows: dict[str, dict[str, float | None]] = {}
    for idx, instrument in enumerate(instruments):
        rows[str(instrument)] = {
            "multiplier": _first_finite([row[idx] for row in multipliers if isinstance(row, list) and idx < len(row)]),
            "lot_size": _first_finite([row[idx] for row in lot_sizes if isinstance(row, list) and idx < len(row)]),
            "margin_ratio": _first_finite([row[idx] for row in margin_ratios if isinstance(row, list) and idx < len(row)]),
        }
    return rows


def _event_fee_rate_rows(payload: dict[str, Any], fee_rate: float = 0.0) -> dict[str, dict[str, float]]:
    instruments = list(payload.get("instruments") or [])
    fee_rates = {}
    for instrument in instruments:
        fee_rates[str(instrument)] = {
            "open": float(fee_rate or 0.0),
            "close": float(fee_rate or 0.0),
            "close_today": float(fee_rate or 0.0),
            "close_yesterday": float(fee_rate or 0.0),
            "total": float(fee_rate or 0.0) * 2.0,
        }
    return fee_rates


def _event_position_contribution_rows(
    *,
    portfolio: dict[str, Any],
    payload: dict[str, Any],
    fee_rate: float,
    collapse_product: bool,
) -> list[dict[str, Any]]:
    position_curve = portfolio.get("position_curve") or {}
    notional_curve = portfolio.get("notional_curve") or {}
    equity_curve = portfolio.get("equity_curve") or {}
    if not position_curve:
        return []
    fee_rows = _event_fee_rate_rows(payload, fee_rate)
    rule_rows = _event_market_rule_rows(payload)
    accum: dict[str, dict[str, Any]] = {}
    timestamps = sorted(position_curve.keys())
    prev_equity: float | None = None
    for timestamp in timestamps:
        positions = position_curve.get(timestamp) or {}
        notionals = notional_curve.get(timestamp) or {}
        equity_raw = equity_curve.get(timestamp)
        try:
            equity = float(equity_raw) if equity_raw is not None else None
        except Exception:
            equity = None
        if equity is None or not math.isfinite(equity):
            continue
        if prev_equity is None or prev_equity <= 0:
            period_return = 0.0
        else:
            period_return = equity / prev_equity - 1.0
        prev_equity = equity
        active_total = 0.0
        active_notionals: dict[str, float] = {}
        for instrument, quantity in positions.items():
            try:
                qty = abs(float(quantity))
            except Exception:
                qty = 0.0
            if qty <= 1e-12:
                continue
            notional = notionals.get(instrument)
            try:
                notional_value = abs(float(notional)) if notional is not None else 0.0
            except Exception:
                notional_value = 0.0
            if notional_value <= 0:
                notional_value = qty
            active_notionals[str(instrument)] = notional_value
            active_total += notional_value
        if active_total <= 0:
            continue
        for instrument, notional_value in active_notionals.items():
            key = _product_parent_name(instrument) if collapse_product else instrument
            row = accum.setdefault(key, {
                "display_ref": key,
                "source_instruments": set(),
                "active_period_count": 0,
                "gross_contribution": 0.0,
                "weight_sum": 0.0,
                "fee_open_sum": 0.0,
                "fee_close_sum": 0.0,
                "fee_close_today_sum": 0.0,
                "fee_close_yesterday_sum": 0.0,
                "multiplier_sum": 0.0,
                "lot_size_sum": 0.0,
                "margin_ratio_sum": 0.0,
            })
            weight = notional_value / active_total
            row["source_instruments"].add(instrument)
            row["active_period_count"] += 1
            row["gross_contribution"] += period_return * weight
            row["weight_sum"] += weight
            fee = fee_rows.get(instrument) or {}
            rules = rule_rows.get(instrument) or {}
            row["fee_open_sum"] += float(fee.get("open") or 0.0) * weight
            row["fee_close_sum"] += float(fee.get("close") or 0.0) * weight
            row["fee_close_today_sum"] += float(fee.get("close_today") or 0.0) * weight
            row["fee_close_yesterday_sum"] += float(fee.get("close_yesterday") or fee.get("close") or 0.0) * weight
            for source, target in (
                ("multiplier", "multiplier_sum"),
                ("lot_size", "lot_size_sum"),
                ("margin_ratio", "margin_ratio_sum"),
            ):
                value = rules.get(source)
                if value is not None and math.isfinite(float(value)):
                    row[target] += float(value) * weight
    rows = []
    for key, item in accum.items():
        weight_sum = float(item["weight_sum"] or 0.0)
        product = _event_instrument_display(key, collapse_product=False)
        product["fee"] = {
            "open": item["fee_open_sum"] / weight_sum if weight_sum else None,
            "close": item["fee_close_sum"] / weight_sum if weight_sum else None,
            "close_today": item["fee_close_today_sum"] / weight_sum if weight_sum else None,
            "close_yesterday": item["fee_close_yesterday_sum"] / weight_sum if weight_sum else None,
            "_is_weighted": bool(collapse_product),
        }
        product["source_names"] = sorted(item["source_instruments"])
        rows.append({
            "product": product,
            "active_period_count": int(item["active_period_count"]),
            "gross_contribution": float(item["gross_contribution"]),
            "mean_active_contribution": (
                float(item["gross_contribution"]) / item["active_period_count"]
                if item["active_period_count"] else None
            ),
            "mean_return": (
                float(item["gross_contribution"]) / item["active_period_count"]
                if item["active_period_count"] else None
            ),
            "market_rule": {
                "multiplier": item["multiplier_sum"] / weight_sum if weight_sum else None,
                "lot_size": item["lot_size_sum"] / weight_sum if weight_sum else None,
                "margin_ratio": item["margin_ratio_sum"] / weight_sum if weight_sum else None,
                "_is_weighted": bool(collapse_product),
            },
        })
    return rows


def _event_product_analysis(portfolio: dict[str, Any], payload: dict[str, Any], strategy_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        fee_rate = float((strategy_settings or {}).get("fee_rate") or 0.0)
    except Exception:
        fee_rate = 0.0
    contract_rows = _event_position_contribution_rows(
        portfolio=portfolio, payload=payload, fee_rate=fee_rate, collapse_product=False,
    )
    product_rows = _event_position_contribution_rows(
        portfolio=portfolio, payload=payload, fee_rate=fee_rate, collapse_product=True,
    )

    def _pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
        top = sorted(rows, key=lambda item: item["gross_contribution"], reverse=True)
        bottom = sorted(rows, key=lambda item: item["gross_contribution"])
        positive_total = sum(max(row["gross_contribution"], 0.0) for row in rows)
        top1_ratio = (top[0]["gross_contribution"] / positive_total) if top and positive_total > 0 else None
        top3_ratio = (
            sum(max(row["gross_contribution"], 0.0) for row in top[:3]) / positive_total
            if positive_total > 0 else None
        )
        return {
            "rows": rows,
            "top_products": top[:10],
            "bottom_products": bottom[:10],
            "top1_positive_contribution_ratio": top1_ratio,
            "top3_positive_contribution_ratio": top3_ratio,
            "is_concentrated": bool(
                (top1_ratio is not None and top1_ratio >= 0.5)
                or (top3_ratio is not None and top3_ratio >= 0.8)
            ),
        }

    product_level = _pack(product_rows)
    contract_level = _pack(contract_rows)
    product_level_copy = dict(product_level)
    product_level["by_level"] = {
        "products": product_level_copy,
        "contracts": contract_level,
    }
    product_level["default_level"] = "products"
    return product_level


def _snapshot_actual_quantity(
    position_row: Any,
    amount_row: Any | None,
    product_idx: int,
    eps: float = 1e-12,
) -> tuple[float, float]:
    """Read quantity and amount directly from simulate's pre-computed arrays.

    NEVER recompute amount from price — amount comes from hold_amounts_np
    (= position_notional in simulate, already using the correct open_price).
    """
    qty = 0.0
    amt = 0.0
    if position_row is not None and product_idx < len(position_row):
        qty_value = _safe_float(position_row[product_idx])
        qty = 0.0 if qty_value is None else qty_value
    if amount_row is not None and product_idx < len(amount_row):
        amt_value = _safe_float(amount_row[product_idx])
        amt = 0.0 if amt_value is None else amt_value
    if abs(qty) <= eps:
        qty = 0.0
    if abs(amt) <= eps:
        amt = 0.0
    return qty, amt


def _money_minor_units_to_major_value(value: Any) -> float | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return float(minor_units_to_major(numeric))


def _money_minor_units_row_to_major(row: Any | None) -> Any | None:
    if row is None:
        return None
    return minor_units_to_major(row)


def _format_money_2(value: Any) -> str:
    numeric = _safe_float(value)
    if numeric is None:
        numeric = 0.0
    return f"{float(numeric):,.2f}"


def _format_money_with_currency(value: Any, currency: str) -> str:
    return f"{normalize_currency(currency)} {_format_money_2(value)}"





def _snapshot_group_label(group_idx: int, group_names: Any) -> str:
    if isinstance(group_names, dict):
        for key in (group_idx, str(group_idx)):
            if key in group_names and group_names[key]:
                return str(group_names[key])
    return f'Group {group_idx + 1}'


def _snapshot_display_timezone(group_result: Any, valid_cols: list[Any] | None = None) -> str:
    index_list = list(getattr(group_result, 'index_list', []) or [])
    for idx_entry in index_list:
        ts = _signal_time(idx_entry)
        if isinstance(ts, pd.Timestamp) and ts.tzinfo is not None:
            return str(ts.tz)
    for product_ref in valid_cols or list(getattr(group_result, 'valid_cols', []) or []):
        product = product_ref if isinstance(product_ref, Product) else _registered_product(str(product_ref))
        timezone = getattr(product, 'timezone', None) if product is not None else None
        if timezone:
            return str(timezone)
    return 'Asia/Shanghai'


def _build_snapshot_matrix(
    *,
    matrix_key: str,
    matrix_label: str,
    group_result: Any,
    valid_cols: list[Any],
    fee_rates_by_name: dict[str, dict[str, float]],
    t_idx: int | None,
    prev_t_idx: int | None,
    capital_diagnostics: dict[str, Any] | None = None,
    group_names: Any = None,
    collapse_term_structure: bool = False,
) -> dict[str, Any]:
    positions = getattr(group_result, 'position_quantities_np', None)
    amounts = getattr(group_result, 'hold_amounts_np', None)
    target_before_floor = getattr(group_result, 'target_amounts_before_floor_np', None)
    prev_end_amounts = getattr(group_result, 'prev_end_amounts_np', None)
    # Per-lot cost arrays from simulate — exactly the values used inside simulate
    # (NEVER recompute from input params; these come directly from the trading book)
    one_lot_margin_np = getattr(group_result, 'one_lot_margin_np', None)
    one_lot_fee_np = getattr(group_result, 'one_lot_fee_np', None)
    memberships = getattr(group_result, 'membership_np', None)
    total_equity_np = getattr(group_result, 'total_equity_np', None)
    cash_np = getattr(group_result, 'cash_np', None)
    pre_rebalance_total_equity_np = getattr(group_result, 'pre_rebalance_total_equity_np', None)
    post_rebalance_total_equity_np = getattr(group_result, 'post_rebalance_total_equity_np', None)
    pre_rebalance_cash_np = getattr(group_result, 'pre_rebalance_cash_np', None)
    post_rebalance_cash_np = getattr(group_result, 'post_rebalance_cash_np', None)
    buy_fee_amount_np = getattr(group_result, 'buy_fee_amount_np', None)
    sell_fee_amount_np = getattr(group_result, 'sell_fee_amount_np', None)
    liquidity_capacity_np = getattr(group_result, 'liquidity_capacity_np', None)
    liquidity_modes = getattr(group_result, 'liquidity_modes', None) or []
    liquidity_percents = getattr(group_result, 'liquidity_percents', None) or []
    base_currency = str(getattr(group_result, 'base_currency', None) or 'CNY').upper()
    product_currency_vec = require_product_currency_vector(
        list(valid_cols or []),
        explicit=getattr(group_result, 'product_currency_vec', None),
        default=None,
    )
    if positions is None and amounts is None:
        return {'key': matrix_key, 'label': matrix_label, 'columns': [], 'rows': [], 'cells': []}

    current_products = list(valid_cols or [])
    row_order: list[str] = []
    row_meta: dict[str, dict[str, Any]] = {}
    per_group: list[dict[str, dict[str, Any]]] = []

    def _product_name(product_ref: Any) -> str:
        return getattr(product_ref, 'name', str(product_ref))

    def _resolved_product(product_ref: Any):
        if collapse_term_structure:
            resolved = None
            try:
                resolved = getattr(product_ref, 'parent_product', None)
                if callable(resolved):
                    resolved = resolved()
            except Exception:
                resolved = None
            if resolved is None:
                resolved = resolve_term_structure_product(product_ref)
            if resolved is None:
                resolved = _cn_futures_contract_parent(product_ref)
            if resolved is not None:
                return resolved
        return product_ref

    def _row_key(raw_product: Any) -> str:
        resolved = _resolved_product(raw_product)
        return _product_name(resolved if resolved is not None else raw_product)

    def _row_display(product_ref: Any, sources: list[str]) -> dict[str, Any]:
        display = _snapshot_product_display(product_ref, fee_rates_by_name, collapsed_from=sources[0] if sources else None)
        if collapse_term_structure and len(sources) > 1:
            display['source_names'] = sources
        return display

    product_rows = []
    raw_name_to_p_idx: dict[str, int] = {}
    for p_idx, raw_product in enumerate(current_products):
        raw_name = _product_name(raw_product)
        resolved_product = _resolved_product(raw_product) if collapse_term_structure else raw_product
        row_key = _product_name(resolved_product if resolved_product is not None else raw_product)
        product_rows.append({
            'raw_product': raw_product,
            'raw_name': raw_name,
            'resolved_product': resolved_product,
            'row_key': row_key,
            'p_idx': p_idx,
        })
        raw_name_to_p_idx[raw_name] = p_idx

    def _group_index_map(index: int) -> tuple[Any, Any, Any, Any, Any, Any]:
        cur_pos = positions[t_idx, index] if positions is not None and t_idx is not None and t_idx < positions.shape[0] else None
        cur_amt = _money_minor_units_row_to_major(amounts[t_idx, index]) if amounts is not None and t_idx is not None and t_idx < amounts.shape[0] else None
        prev_pos = positions[prev_t_idx, index] if positions is not None and prev_t_idx is not None and prev_t_idx < positions.shape[0] else None
        prev_amt = (
            _money_minor_units_row_to_major(prev_end_amounts[t_idx, index])
            if prev_end_amounts is not None and t_idx is not None and t_idx < prev_end_amounts.shape[0]
            else _money_minor_units_row_to_major(amounts[prev_t_idx, index]) if amounts is not None and prev_t_idx is not None and prev_t_idx < amounts.shape[0]
            else None
        )
        cur_mem = memberships[t_idx, index] if memberships is not None and t_idx is not None and t_idx < memberships.shape[0] else None
        prev_mem = memberships[prev_t_idx, index] if memberships is not None and prev_t_idx is not None and prev_t_idx < memberships.shape[0] else None
        return (cur_pos, cur_amt, prev_pos, prev_amt, cur_mem, prev_mem)

    diagnostics_by_group: dict[int, dict[str, Any]] = {}
    if isinstance(capital_diagnostics, dict):
        for item in capital_diagnostics.get('blocked_groups', []) or []:
            try:
                diagnostics_by_group[int(item.get('group_index'))] = item
            except (TypeError, ValueError, AttributeError):
                continue

    group_count = 0
    for matrix in (positions, amounts, memberships):
        if matrix is not None and getattr(matrix, 'ndim', 0) >= 2:
            group_count = int(matrix.shape[1])
            break

    for g_idx in range(group_count):
        cur_pos, cur_amt, prev_pos, prev_amt, cur_mem, prev_mem = _group_index_map(g_idx)
        group_rows: dict[str, dict[str, Any]] = {}
        for p_idx, product_row in enumerate(product_rows):
            raw_product = product_row['raw_product']
            raw_name = product_row['raw_name']
            row_key = product_row['row_key']
            resolved_product = product_row['resolved_product']
            product_currency = str(product_currency_vec[p_idx]).upper()
            cur_qty, cur_amount = _snapshot_actual_quantity(cur_pos, cur_amt, p_idx)
            prev_qty, prev_amount = _snapshot_actual_quantity(prev_pos, prev_amt, p_idx)
            if row_key not in group_rows:
                group_rows[row_key] = {
                    'name': row_key,
                    'source_names': [raw_name],
                    'current_qty': 0.0,
                    'current_amount': 0.0,
                    'prev_qty': 0.0,
                    'prev_amount': 0.0,
                    'current_membership': False,
                    'prev_membership': False,
                    'target_budget_amount': 0.0,
                    'planned_qty': 0.0,
                    'planned_amount': 0.0,
                    'one_lot_margin': 0.0,
                    'one_lot_fee': 0.0,
                    'currency': product_currency,
                    'display': _row_display(resolved_product if resolved_product is not None else raw_product, [raw_name]),
                }
                if row_key not in row_order:
                    row_order.append(row_key)
                    row_meta[row_key] = group_rows[row_key]['display']
            else:
                if raw_name not in group_rows[row_key]['source_names']:
                    group_rows[row_key]['source_names'].append(raw_name)
                    group_rows[row_key]['display'] = _row_display(resolved_product if resolved_product is not None else raw_product, group_rows[row_key]['source_names'])
                    row_meta[row_key] = group_rows[row_key]['display']
            group_rows[row_key]['current_qty'] += cur_qty
            group_rows[row_key]['current_amount'] += cur_amount
            group_rows[row_key]['prev_qty'] += prev_qty
            group_rows[row_key]['prev_amount'] += prev_amount
            if cur_mem is not None and p_idx < len(cur_mem):
                group_rows[row_key]['current_membership'] = bool(group_rows[row_key]['current_membership'] or bool(cur_mem[p_idx]))
            if prev_mem is not None and p_idx < len(prev_mem):
                group_rows[row_key]['prev_membership'] = bool(group_rows[row_key]['prev_membership'] or bool(prev_mem[p_idx]))
            target_amount_value = None
            if target_before_floor is not None and t_idx is not None and t_idx < target_before_floor.shape[0] and g_idx < target_before_floor.shape[1] and p_idx < target_before_floor.shape[2]:
                target_amount_value = _money_minor_units_to_major_value(target_before_floor[t_idx, g_idx, p_idx])
            if target_amount_value is not None:
                group_rows[row_key]['target_budget_amount'] += float(target_amount_value)
            # planned_qty/planned_amount come directly from simulate arrays, NOT recomputed:
            # - position_quantities_np = desired_quantities (after full pipeline:
            #   liquidity cap → floor → cash packing)
            # - hold_amounts_np = position_notional (= desired_quantities × open_price contract value)
            if positions is not None and t_idx is not None and t_idx < positions.shape[0] and g_idx < positions.shape[1] and p_idx < positions.shape[2]:
                sim_planned_qty = _safe_float(positions[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['planned_qty'] += float(sim_planned_qty)
            if amounts is not None and t_idx is not None and t_idx < amounts.shape[0] and g_idx < amounts.shape[1] and p_idx < amounts.shape[2]:
                sim_planned_amount = _money_minor_units_to_major_value(amounts[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['planned_amount'] += float(sim_planned_amount)
            # one_lot_margin / one_lot_fee: read directly from simulate-computed arrays
            # (same values used inside _pack_openable_quantities / _row_required_capital).
            # Used for diagnostic display to show per-lot budget;
            # NEVER used for planned_qty computation.
            if one_lot_margin_np is not None and t_idx is not None and t_idx < one_lot_margin_np.shape[0] and g_idx < one_lot_margin_np.shape[1] and p_idx < one_lot_margin_np.shape[2]:
                sim_one_lot_margin = _safe_float(one_lot_margin_np[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['one_lot_margin'] = max(group_rows[row_key]['one_lot_margin'], float(sim_one_lot_margin))
            if one_lot_fee_np is not None and t_idx is not None and t_idx < one_lot_fee_np.shape[0] and g_idx < one_lot_fee_np.shape[1] and p_idx < one_lot_fee_np.shape[2]:
                sim_one_lot_fee = _safe_float(one_lot_fee_np[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['one_lot_fee'] = max(group_rows[row_key]['one_lot_fee'], float(sim_one_lot_fee))
        per_group.append(group_rows)

    columns = []
    for g_idx in range(len(per_group)):
        current_active = 0
        selected_count = 0
        for row_key, row in per_group[g_idx].items():
            if abs(row['current_qty']) > 1e-12 or abs(row['current_amount']) > 1e-12:
                current_active += 1
            if bool(row.get('current_membership')):
                selected_count += 1
        label = _snapshot_group_label(g_idx, group_names)
        columns.append({
            'name': label,
            'label': label,
            'index': g_idx,
            'count': selected_count,
            'count_label': f'持仓品种数({selected_count})',
        })

    cells = []
    summary_cells = []
    summary_keys = []

    def _matrix_value(matrix: Any, g_idx: int) -> float | None:
        if matrix is None or t_idx is None or t_idx >= matrix.shape[0] or g_idx >= matrix.shape[1]:
            return None
        return _money_minor_units_to_major_value(matrix[t_idx, g_idx])

    def _append_amount_row(
        row_key: str,
        display: dict[str, Any],
        end_matrix: Any,
        *,
        pre_rebalance_matrix: Any | None = None,
        post_rebalance_matrix: Any | None = None,
        buy_fee_matrix: Any | None = None,
        sell_fee_matrix: Any | None = None,
    ) -> None:
        if end_matrix is None or t_idx is None or t_idx >= end_matrix.shape[0]:
            return
        amount_cells = []
        for g_idx in range(len(per_group)):
            end_amount = _matrix_value(end_matrix, g_idx)
            pre_rebalance_amount = _matrix_value(pre_rebalance_matrix, g_idx)
            post_rebalance_amount = _matrix_value(post_rebalance_matrix, g_idx)
            if prev_t_idx is not None and prev_t_idx < end_matrix.shape[0] and g_idx < end_matrix.shape[1]:
                previous_end_amount = _money_minor_units_to_major_value(end_matrix[prev_t_idx, g_idx])
                if pre_rebalance_amount is None:
                    pre_rebalance_amount = previous_end_amount
                if post_rebalance_amount is None:
                    post_rebalance_amount = previous_end_amount
            end_amount = 0.0 if end_amount is None else end_amount
            pre_rebalance_amount = end_amount if pre_rebalance_amount is None else pre_rebalance_amount
            post_rebalance_amount = pre_rebalance_amount if post_rebalance_amount is None else post_rebalance_amount
            buy_fee_amount = _matrix_value(buy_fee_matrix, g_idx)
            sell_fee_amount = _matrix_value(sell_fee_matrix, g_idx)
            buy_fee_amount = 0.0 if buy_fee_amount is None else buy_fee_amount
            sell_fee_amount = 0.0 if sell_fee_amount is None else sell_fee_amount
            delta_amount = end_amount - post_rebalance_amount
            if delta_amount > 1e-12:
                status = 'increasing'
                direction = 'increase'
            elif delta_amount < -1e-12:
                status = 'decreasing'
                direction = 'decrease'
            else:
                status = 'holding'
                direction = 'flat'
            amount_cells.append({
                'status': status,
                'product': display,
                'currency': base_currency,
                'quantity': None,
                'amount': round(float(end_amount), 2),
                'pre_rebalance_amount': round(float(pre_rebalance_amount), 2),
                'post_rebalance_amount': round(float(post_rebalance_amount), 2),
                'end_amount': round(float(end_amount), 2),
                'buy_fee_amount': round(float(buy_fee_amount), 2),
                'sell_fee_amount': round(float(sell_fee_amount), 2),
                'fee_amount': round(float(buy_fee_amount + sell_fee_amount), 2),
                'previous_quantity': None,
                'delta_quantity': None,
                'delta_amount': round(float(delta_amount), 2),
                'change_direction': direction,
                'pending_exit': False,
                'source_names': [],
            })
        row_meta[row_key] = display
        summary_keys.append(row_key)
        summary_cells.append(amount_cells)

    _append_amount_row(
        '__total_equity__',
        {'name': '总资产'},
        total_equity_np,
        pre_rebalance_matrix=pre_rebalance_total_equity_np,
        post_rebalance_matrix=post_rebalance_total_equity_np,
        buy_fee_matrix=buy_fee_amount_np,
        sell_fee_matrix=sell_fee_amount_np,
    )
    _append_amount_row(
        '__cash__',
        {'name': '现金'},
        cash_np,
        pre_rebalance_matrix=pre_rebalance_cash_np,
        post_rebalance_matrix=post_rebalance_cash_np,
        buy_fee_matrix=buy_fee_amount_np,
        sell_fee_matrix=sell_fee_amount_np,
    )

    for row_key in row_order:
        row_cells = []
        row_display = row_meta.get(row_key) or _snapshot_product_display(row_key)
        for g_idx in range(len(per_group)):
            row = per_group[g_idx].get(row_key)
            if not row:
                row_cells.append({
                    'status': 'absent',
                    'product': None,
                    'quantity': 0.0,
                    'amount': 0.0,
                    'pending_exit': False,
                    'selected': False,
                    'open_reason': None,
                })
                continue
            cur_active = abs(row['current_qty']) > 1e-12 or abs(row['current_amount']) > 1e-12
            prev_active = abs(row['prev_qty']) > 1e-12 or abs(row['prev_amount']) > 1e-12
            desired_now = bool(row['current_membership'])
            desired_prev = bool(row['prev_membership'])
            delta_qty = row['current_qty'] - row['prev_qty']
            delta_amount = row['current_amount'] - row['prev_amount']
            diag = diagnostics_by_group.get(g_idx)
            open_reason = None
            planned_qty = row.get('planned_qty') or 0.0
            planned_amount = row.get('planned_amount') or 0.0
            target_budget_amount = row.get('target_budget_amount') or 0.0
            one_lot_margin = row.get('one_lot_margin') or 0.0
            one_lot_fee = row.get('one_lot_fee') or 0.0
            one_lot_required_cash = one_lot_margin + one_lot_fee
            remaining_cash = None
            if post_rebalance_cash_np is not None and t_idx is not None:
                try:
                    if 0 <= t_idx < post_rebalance_cash_np.shape[0] and 0 <= g_idx < post_rebalance_cash_np.shape[1]:
                        remaining_cash = _money_minor_units_to_major_value(post_rebalance_cash_np[t_idx, g_idx])
                except Exception:
                    remaining_cash = None
            if desired_now and not cur_active:
                # selected but not opened — diagnose with per-lot budget + simulate data
                reasons = []
                if remaining_cash is not None:
                    reasons.append(f"剩余现金 {_format_money_with_currency(remaining_cash, base_currency)}")
                if one_lot_required_cash > 0:
                    reasons.append(
                        f"一手估算 {_format_money_with_currency(one_lot_required_cash, base_currency)}"
                        f"（保证金 {_format_money_with_currency(one_lot_margin, base_currency)}"
                        f" + 手续费 {_format_money_with_currency(one_lot_fee, base_currency)}）"
                    )
                if target_budget_amount > 0:
                    reasons.append(f"目标预算 {_format_money_with_currency(target_budget_amount, base_currency)}")
                if planned_qty < 1e-12 and target_budget_amount > 0 and remaining_cash is not None:
                    if remaining_cash >= target_budget_amount and one_lot_required_cash > target_budget_amount:
                        reasons.append(
                            f"目标预算 {_format_money_with_currency(target_budget_amount, base_currency)}"
                            f" < 一手估算 {_format_money_with_currency(one_lot_required_cash, base_currency)}，不足以开1手"
                        )
                    elif remaining_cash >= one_lot_required_cash:
                        reasons.append(f"流动性限额限制：目标预算 {_format_money_with_currency(target_budget_amount, base_currency)} → floor后0手")
                    else:
                        reasons.append(
                            f"剩余现金 {_format_money_with_currency(remaining_cash, base_currency)}"
                            f" < 一手估算 {_format_money_with_currency(one_lot_required_cash, base_currency)}，资金不足"
                        )
                open_reason = '；'.join(reasons) if reasons else '资金不足以开仓'

            if desired_now and not cur_active:
                status = 'selected'
            elif cur_active and not prev_active:
                status = 'entering'
            elif prev_active and not cur_active:
                status = 'exiting'
            elif cur_active and not desired_now and (desired_prev or prev_active):
                status = 'pending_exit'
            elif cur_active and prev_active and delta_qty > 1e-12:
                status = 'increasing'
            elif cur_active and prev_active and delta_qty < -1e-12:
                status = 'decreasing'
            elif cur_active:
                status = 'holding'
            else:
                status = 'absent'
            if delta_qty > 1e-12 or delta_amount > 1e-12:
                change_direction = 'increase'
            elif delta_qty < -1e-12 or delta_amount < -1e-12:
                change_direction = 'decrease'
            else:
                change_direction = 'flat'
            # Compute per-product liquidity cap amount for this time step
            liquidity_cap_amount = None
            if liquidity_capacity_np is not None and liquidity_modes and liquidity_percents:
                try:
                    # Use the first source product's p_idx to look up liquidity cap
                    source_names = row.get('source_names', [])
                    first_name = source_names[0] if source_names else row_key
                    first_p_idx = raw_name_to_p_idx.get(first_name)
                    if (first_p_idx is not None
                        and 0 <= g_idx < len(liquidity_modes)
                        and liquidity_modes[g_idx] == 'percent'
                        and t_idx is not None
                        and 0 <= t_idx < liquidity_capacity_np.shape[0]
                        and 0 <= g_idx < liquidity_capacity_np.shape[1]
                        and 0 <= first_p_idx < liquidity_capacity_np.shape[2]):
                        raw_cap = _safe_float(liquidity_capacity_np[t_idx, g_idx, first_p_idx])
                        if raw_cap is not None and np.isfinite(raw_cap) and raw_cap > 0:
                            liquidity_cap_amount = round(float(raw_cap), 2)
                except Exception:
                    pass

            row_cells.append({
                'status': status,
                'product': row_display,
                'currency': row['currency'],
                'quantity': round(float(row['current_qty']), 6),
                'amount': round(float(row['current_amount']), 2),
                'previous_quantity': round(float(row['prev_qty']), 6),
                'previous_amount': round(float(row['prev_amount']), 2),
                'delta_quantity': round(float(delta_qty), 6),
                'delta_amount': round(float(delta_amount), 2),
                'change_direction': change_direction,
                'pending_exit': status == 'pending_exit',
                'selected': bool(desired_now and not cur_active),
                'open_reason': open_reason,
                'planned_qty': round(float(planned_qty), 6),
                'planned_amount': round(float(planned_amount), 2),
                'target_budget_amount': round(float(target_budget_amount), 2),
                'one_lot_margin': round(float(one_lot_margin), 2),
                'one_lot_fee': round(float(one_lot_fee), 2),
                'one_lot_required_cash': round(float(one_lot_required_cash), 2),
                'liquidity_cap_amount': liquidity_cap_amount,
                'source_names': row.get('source_names', []),
            })
        cells.append(row_cells)

    return {
        'key': matrix_key,
        'label': matrix_label,
        'columns': columns,
        'rows': [row_meta[k] for k in summary_keys] + [row_meta[k] for k in row_order],
        'cells': summary_cells + cells,
    }


def _build_snapshot_matrices(group_result: Any, valid_cols: list[str], fee_rates_by_name: dict[str, dict[str, float]], t_idx: int | None, prev_t_idx: int | None, capital_diagnostics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    group_names = getattr(group_result, 'group_names', None) or {}
    return [
        _build_snapshot_matrix(
            matrix_key='raw',
            matrix_label='全产品',
            group_result=group_result,
            valid_cols=valid_cols,
            fee_rates_by_name=fee_rates_by_name,
            t_idx=t_idx,
            prev_t_idx=prev_t_idx,
            capital_diagnostics=capital_diagnostics,
            group_names=group_names,
            collapse_term_structure=False,
        ),
        _build_snapshot_matrix(
            matrix_key='collapsed',
            matrix_label='期限折叠',
            group_result=group_result,
            valid_cols=valid_cols,
            fee_rates_by_name=fee_rates_by_name,
            t_idx=t_idx,
            prev_t_idx=prev_t_idx,
            capital_diagnostics=capital_diagnostics,
            group_names=group_names,
            collapse_term_structure=True,
        ),
    ]


def _snapshot_change_indices(group_result: Any) -> list[int]:
    positions = getattr(group_result, 'position_quantities_np', None)
    memberships = getattr(group_result, 'membership_np', None)
    source = positions if positions is not None else memberships
    if source is None:
        return []
    try:
        arr = np.asarray(source)
        if arr.ndim != 3 or arr.shape[0] < 2:
            return []
        if arr.dtype == np.bool_:
            changed = np.any(arr[1:] != arr[:-1], axis=(1, 2))
        else:
            arr = np.nan_to_num(np.asarray(arr, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
            changed = np.any(np.abs(arr[1:] - arr[:-1]) > 1e-12, axis=(1, 2))
        return [idx + 1 for idx, value in enumerate(changed) if bool(value)]
    except Exception:
        return []


def _latest_group_result(tester: Any):
    """Return the latest available GroupRunResult from a tester."""
    if tester is None:
        return None

    results = getattr(tester, 'results', None)
    if not isinstance(results, dict) or not results:
        return None

    last_factor = getattr(tester, 'last_group_factor', None)
    if last_factor is not None:
        last_result = results.get(last_factor)
        if last_result is not None and getattr(last_result, 'group_result', None) is not None:
            return last_result.group_result

    for _factor, result in reversed(list(results.items())):
        group_result = getattr(result, 'group_result', None)
        if group_result is not None:
            return group_result

    return None


def _build_zero_position_warning(group_result: Any) -> str | None:
    """Explain when the first rebalance cannot open any position."""
    diagnostics = _build_zero_position_diagnostics(group_result)
    return diagnostics['warning'] if diagnostics else None


def _build_zero_position_diagnostics(group_result: Any) -> dict[str, Any] | None:
    """Return a compact explanation when the first rebalance opens no positions."""
    if group_result is None:
        return None
    quantities = getattr(group_result, 'position_quantities_np', None)
    membership = getattr(group_result, 'membership_np', None)
    prices = getattr(group_result, 'price_np', None)
    point_values = getattr(group_result, 'point_value_mat', None)
    lot_sizes = getattr(group_result, 'min_trade_quantity_mat', None)
    open_ratios = getattr(group_result, 'open_ratio_mat', None)
    open_fixed = getattr(group_result, 'open_fixed_mat', None)
    margin_ratios = getattr(group_result, 'margin_ratio_mat', None)
    margin_flags = getattr(group_result, 'is_margin_traded_vec', None)
    initial_capital = getattr(group_result, 'initial_capital', None)
    base_currency = normalize_currency(getattr(group_result, 'base_currency', None), 'CNY')
    if quantities is None or membership is None or prices is None:
        return None
    if getattr(quantities, 'size', 0) == 0 or getattr(membership, 'size', 0) == 0 or getattr(prices, 'size', 0) == 0:
        return None
    initial_capital_value = _safe_float(initial_capital)
    if initial_capital_value is None:
        return None

    def _coerce_1d(values: Any, length: int, default: float = 0.0, *, dtype=float) -> np.ndarray:
        arr = np.asarray(values if values is not None else [], dtype=dtype).reshape(-1)
        if arr.size == length:
            return arr
        out = np.full(length, default, dtype=dtype)
        if arr.size > 0:
            limit = min(arr.size, length)
            out[:limit] = arr[:limit]
        return out

    first_membership = np.asarray(membership[0], dtype=bool)
    first_quantities = np.asarray(quantities[0], dtype=float)
    if first_membership.ndim != 2 or first_quantities.ndim != 2:
        return None

    group_count, product_count = first_membership.shape
    price_row = np.asarray(prices[0], dtype=float).reshape(-1)
    if price_row.size != product_count:
        price_row = _coerce_1d(price_row, product_count, default=np.nan)

    def _first_rule_row(values: Any, default: float) -> np.ndarray:
        if values is None:
            return np.full(product_count, default, dtype=float)
        matrix = np.asarray(values, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != product_count or matrix.shape[0] == 0:
            return np.full(product_count, default, dtype=float)
        return matrix[0]

    point_values_row = _first_rule_row(point_values, 1.0)
    lot_sizes_row = _first_rule_row(lot_sizes, 1.0)
    open_ratio_row = _first_rule_row(open_ratios, 0.0)
    open_fixed_row = _first_rule_row(open_fixed, 0.0)
    margin_ratio_row = _first_rule_row(margin_ratios, 1.0)
    margin_flag_row = _coerce_1d(margin_flags, product_count, default=False, dtype=bool)
    valid_cols = list(getattr(group_result, 'valid_cols', None) or [])
    group_names = getattr(group_result, 'group_names', None) or {}

    def _group_name(group_index: int) -> str:
        raw = group_names.get(group_index, group_index)
        try:
            return str(raw)
        except Exception:
            return f'第{group_index + 1}组'

    blocked_groups: list[dict[str, Any]] = []
    for g_idx in range(group_count):
        wants_position = first_membership[g_idx]
        if not wants_position.any():
            continue
        has_position = np.any(np.abs(first_quantities[g_idx]) > 1e-12)
        if has_position:
            continue

        active_products = np.where(wants_position)[0]
        if active_products.size == 0:
            continue
        budget_per_product = initial_capital_value / float(active_products.size)
        candidates: list[dict[str, Any]] = []
        for p_idx in active_products:
            price_value = _safe_float(price_row[p_idx]) if p_idx < price_row.size else None
            point_value = _safe_float(point_values_row[p_idx]) if p_idx < point_values_row.size else None
            lot_size = _safe_float(lot_sizes_row[p_idx]) if p_idx < lot_sizes_row.size else None
            open_ratio = _safe_float(open_ratio_row[p_idx]) if p_idx < open_ratio_row.size else 0.0
            open_fee_fixed = _safe_float(open_fixed_row[p_idx]) if p_idx < open_fixed_row.size else 0.0
            margin_ratio = _safe_float(margin_ratio_row[p_idx]) if p_idx < margin_ratio_row.size else None
            if price_value is None or point_value is None or lot_size is None:
                continue
            contract_value = price_value * point_value * lot_size
            if not math.isfinite(contract_value) or contract_value <= 0:
                continue
            occupied = contract_value * (margin_ratio if bool(margin_flag_row[p_idx]) and margin_ratio is not None else 1.0)
            fee = contract_value * float(open_ratio or 0.0) + lot_size * float(open_fee_fixed or 0.0)
            required = occupied + fee
            candidates.append({
                'product_index': int(p_idx),
                'product_name': valid_cols[p_idx] if p_idx < len(valid_cols) else f'#{p_idx}',
                'required_capital': float(required),
                'contract_value': float(contract_value),
                'occupied_capital': float(occupied),
                'fee_capital': float(fee),
                'diagnostic_type': 'estimated',
            })

        if not candidates:
            blocked_groups.append({
                'group_index': int(g_idx),
                'group_name': _group_name(g_idx),
                'active_count': int(active_products.size),
                'budget_per_product': float(budget_per_product),
                'cheapest_product_name': None,
                'cheapest_required_capital': None,
                'cheapest_occupied_capital': None,
                'cheapest_fee_capital': None,
                'diagnostic_type': 'missing_trade_spec',
            })
            continue

        cheapest = min(candidates, key=lambda item: item['required_capital'])
        if budget_per_product + 1e-12 < cheapest['required_capital']:
            blocked_groups.append({
                'group_index': int(g_idx),
                'group_name': _group_name(g_idx),
                'active_count': int(active_products.size),
                'budget_per_product': float(budget_per_product),
                'cheapest_product_name': cheapest['product_name'],
                'cheapest_required_capital': float(cheapest['required_capital']),
                'cheapest_occupied_capital': float(cheapest['occupied_capital']),
                'cheapest_fee_capital': float(cheapest['fee_capital']),
                'diagnostic_type': 'capital_shortage',
            })

    if not blocked_groups:
        return None

    first = blocked_groups[0]
    capital_text = _format_money_with_currency(initial_capital_value, base_currency)
    budget_text = _format_money_with_currency(first['budget_per_product'], base_currency)
    if first.get('diagnostic_type') == 'missing_trade_spec' or first.get('cheapest_required_capital') is None:
        warning = (
            f"首期有 {len(blocked_groups)} 个组未能开出任何仓位。"
            f"按等权分配后，每个活跃品种可分到的预算约 {budget_text}，"
            f"但当前结果里缺少完整的合约价值或费率字段，无法精确反推首手需求；"
            f"从实际持仓看，目标仓位已经被压成 0。"
            f"当前初始金额为 {capital_text}。"
        )
    else:
        required_text = _format_money_with_currency(first['cheapest_required_capital'], base_currency)
        warning = (
            f"首期有 {len(blocked_groups)} 个组未能开出任何仓位。"
            f"按等权分配后，每个活跃品种可分到的预算约 {budget_text}，"
            f"但 {first['group_name']} 里最便宜的品种 {first['cheapest_product_name']} 的一手资金需求约 {required_text}，"
            f"因此目标仓位在最小手数上被压成 0。"
            f"当前初始金额为 {capital_text}。"
        )
    return {
        'warning': warning,
        'initial_capital': float(initial_capital_value),
        'blocked_group_count': int(len(blocked_groups)),
        'blocked_groups': blocked_groups,
    }


def _get_or_create_group_test_tester(page_uuid: str) -> "FactorTester":
    """Page-scoped singleton -- one FactorTester per page dispatches the
    "backtest" task, not one per product_path_selection like the old
    per-selection loop. A later snapshot/detail request on the same page
    looks up this same instance to read back state.account."""
    if page_uuid:
        existing = runtime_state.find_page_object(
            runtime_state.FACTOR_TESTER, "group_test", page_uuid=page_uuid)
        if existing is not None:
            return existing
    tester = FactorTester(products=[], alias="group_test")
    if page_uuid:
        runtime_state.register_page_object(runtime_state.FACTOR_TESTER, tester, page_uuid=page_uuid)
    return tester


def _group_execution_for_request(data: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve event execution from job artifacts.

    ``page_uuid`` may carry a latest-view projection, but page runtime is not
    the canonical owner of job results or lifecycle.
    """
    from server.jobs.artifacts import load_json_artifact
    from server.jobs.repository import JobRepository
    from server.jobs.states import JobStatus

    job_id = str(data.get("job_id") or "").strip()
    run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
    if job_id or run_id:
        owner = str(current_user() or "")
        repository = JobRepository()
        if job_id:
            job = repository.require(job_id, owner=owner)
        else:
            jobs = repository.list(
                owner=owner,
                run_id=run_id,
                kind="backtest",
                statuses=(JobStatus.SUCCEEDED,),
                limit=20,
            )
            if not jobs:
                raise LookupError("指定 run 尚无成功的分组测试 job")
            job = jobs[0]
        artifact = repository.load_artifact(
            job_id=job.job_id,
            name="group_execution",
            owner=owner,
        )
        if not artifact or artifact["state"] != "active":
            raise LookupError("指定 job 尚无可读取的分组测试详情")
        execution = load_json_artifact(
            str(artifact["relative_path"]),
            str(artifact["content_hash"]),
        )
        if not isinstance(execution, dict):
            raise TypeError("分组测试详情文件格式错误")
        return execution
    return None


def _strategy_analysis_for_request(data: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the retained primitives used by lazy strategy-analysis tabs."""
    from server.jobs.artifacts import load_json_artifact
    from server.jobs.repository import JobRepository
    from server.jobs.states import JobStatus

    job_id = str(data.get("job_id") or "").strip()
    run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
    if not job_id and not run_id:
        return None
    owner = str(current_user() or "")
    repository = JobRepository()
    if job_id:
        job = repository.require(job_id, owner=owner)
    else:
        jobs = repository.list(
            owner=owner,
            run_id=run_id,
            kind="backtest",
            statuses=(JobStatus.SUCCEEDED,),
            limit=20,
        )
        if not jobs:
            raise LookupError("指定 run 尚无成功的回测 job")
        job = jobs[0]
    artifact = repository.load_artifact(
        job_id=job.job_id,
        name="strategy_analysis_source",
        owner=owner,
    )
    if not artifact or artifact["state"] != "active":
        raise LookupError(
            "该任务的运行配置版本未保存策略分析数据，请用当前版本重新运行"
        )
    value = load_json_artifact(
        str(artifact["relative_path"]),
        str(artifact["content_hash"]),
    )
    if not isinstance(value, dict) or value.get("artifact_version") != 1:
        raise ValueError("策略分析数据版本不兼容，请用当前版本重新运行")
    return value


def _strategy_analysis_execution(source: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the bounded execution view consumed by existing analyzers."""
    strategies = source.get("strategies") or {}
    portfolios = {}
    owners = []
    for strategy_id, row in strategies.items():
        identity = dict(row.get("identity") or {})
        identity.setdefault("strategy_id", strategy_id)
        owners.append(identity)
        group = row.get("result_group") or {}
        timestamps = list(group.get("timestamps") or ())
        equities = list(group.get("total_equity") or ())
        curve = {
            pd.Timestamp(int(timestamp), unit="ms", tz="UTC").isoformat(): float(value)
            for timestamp, value in zip(timestamps, equities)
        }
        portfolios[strategy_id] = {
            "equity_curve": curve,
            "display_equity_curve": curve,
            "position_curve": dict(row.get("position_curve") or {}),
            "notional_curve": dict(row.get("notional_curve") or {}),
            "margin_curve": dict(row.get("margin_curve") or {}),
            "fill_turnover": dict(row.get("fill_turnover") or {}),
        }
    context = source.get("detail_context") or {}
    return {
        "engine_result": {
            "engine": str(source.get("engine") or ""),
            "portfolios": portfolios,
        },
        "group_owner": owners,
        "serialized_execution": {
            "groups": [dict(row.get("result_group") or {}) for row in strategies.values()],
            "metrics": dict(source.get("metrics") or {}),
        },
        "detail_context": context,
        "payload": dict(context.get("payload") or {}),
        "settings_by_strategy": dict(context.get("settings_by_strategy") or {}),
    }


def _retained_strategy_detail(
    source: dict[str, Any], data: dict[str, Any], group_index: int,
) -> dict[str, Any]:
    strategies = source.get("strategies") or {}
    group_id = str(data.get("group_id") or "")
    if group_id and group_id in strategies:
        return _event_group_detail(
            _strategy_analysis_execution(source),
            str(data.get("product_path_selection_id") or ""),
            group_index,
            group_id=group_id,
        )
    product_selection = str(data.get("product_path_selection_id") or "")
    matches = [
        row for row in strategies.values()
        if str((row.get("identity") or {}).get("product_path_selection_id") or "")
        == product_selection
        and int((row.get("identity") or {}).get("group_index") or 0)
        == group_index
    ]
    if len(matches) != 1:
        raise ValueError("无法在策略分析数据中唯一定位所选策略")
    selected_id = str((matches[0].get("identity") or {}).get("strategy_id") or "")
    return _event_group_detail(
        _strategy_analysis_execution(source),
        product_selection,
        group_index,
        group_id=selected_id,
    )


def _request_has_group_job_selector(data: dict[str, Any]) -> bool:
    return bool(
        str(data.get("job_id") or "").strip()
        or str(data.get("run_id") or data.get("run_token") or "").strip()
    )


@sft_bp.route('/get_group_snapshot', methods=['POST'])
def get_group_snapshot():
    """获取某个时刻各分组的产品列表及与上一时刻的进出变化。
    
    请求参数：
        product_path_selection_id : 产品路径选择 ID
        timestamp_ms              : 目标时刻（UTC epoch 毫秒）
    
    返回：{
        groups: [{
            name, 
            products: [...],        // 当前持仓
            products_in: [...],     // 新进（上一时刻没有，当前有）
            products_out: [...],    // 退出（上一时刻有，当前没有）
            turnover_rate: float,   // 换手率
        }, ...]
    }
    """
    data = request.get_json()
    product_path_selection_id = data.get('product_path_selection_id')
    timestamp_ms  = data.get('timestamp_ms')
    page_uuid = str(data.get('page_uuid') or '')
    if not product_path_selection_id or not timestamp_ms:
        return jsonify({'success': False, 'error': '缺少 product_path_selection_id 或 timestamp_ms'}), 400

    try:
        if page_uuid and not _request_has_group_job_selector(data) and runtime_state.get_page_owner(page_uuid) != current_user():
            return jsonify({'success': False, 'error': 'page_uuid 不属于当前用户'}), 403
        event_execution = _group_execution_for_request(data)
        if event_execution:
            return jsonify(_event_group_snapshot(
                event_execution,
                str(product_path_selection_id),
                int(timestamp_ms),
                data.get("event_cursor"),
            ))
        tester = runtime_state.get_page_object(runtime_state.FACTOR_TESTER, 
            product_path_selection_id, caller='get_group_snapshot', page_uuid=page_uuid
        )

        group_result = _latest_group_result(tester)
        valid_cols_raw = group_result.valid_cols if group_result is not None else None
        index_list = list(getattr(group_result, 'index_list', []) or [])
        if group_result is None or not _safe_bool(valid_cols_raw) or not index_list:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400

        time_entries = index_list

        def _epoch_seconds(value):
            ts = _signal_time(value)
            if isinstance(ts, pd.Timestamp):
                return float(to_epoch_ms(ts, display_timezone) / 1000.0)
            if hasattr(ts, 'timestamp'):
                return float(to_epoch_ms(pd.Timestamp(ts), display_timezone) / 1000.0)
            return float(ts)

        display_timezone = _snapshot_display_timezone(group_result, list(valid_cols_raw or []))
        time_epochs = np.array([_epoch_seconds(idx_entry) for idx_entry in time_entries], dtype=float)

        # 前端传来的 UTC epoch 毫秒
        target_epoch = float(timestamp_ms) / 1000.0

        # 找最近的
        best_pos = int(np.argmin(np.abs(time_epochs - target_epoch)))
        best_idx_entry = time_entries[best_pos]

        # 找到上一时刻 — 用 all_times 的 epoch 排序（避免 tuple/array 直接比较）
        # 用 enumerate 添加位置索引作为 tiebreaker，防止 sorted 回退到 tuple 比较
        # （idx_entry 可能为包含 numpy 类型的 tuple，其 __eq__ 会触发 ambiguous truth value）
        sorted_pos = np.argsort(time_epochs, kind='stable')
        current_pos = int(np.flatnonzero(sorted_pos == best_pos)[0]) if sorted_pos.size else 0
        prev_entry = time_entries[int(sorted_pos[current_pos - 1])] if current_pos > 0 else None

        # (ts_epoch, idx_entry) 对列表，供 all_timestamps_ms 构建和前/后导航使用
        all_times = list(zip(time_epochs, time_entries))

        fee_rates_by_name = _product_fee_rates_by_name(group_result)
        positions = getattr(group_result, 'position_quantities_np', None)
        hold_np = getattr(group_result, 'hold_amounts_np', None)
        capital_diagnostics = _build_zero_position_diagnostics(group_result)
        t_idx = None
        if index_list:
            try:
                t_idx = index_list.index(best_idx_entry)
            except ValueError:
                t_idx = None
        prev_t_idx = None
        if prev_entry is not None:
            try:
                prev_t_idx = index_list.index(prev_entry)
            except ValueError:
                prev_t_idx = None

        valid_cols_list = list(group_result.valid_cols) if group_result.valid_cols else []
        matrices = _build_snapshot_matrices(group_result, valid_cols_list, fee_rates_by_name, t_idx, prev_t_idx, capital_diagnostics)

        # 统计当前真实持仓变动，作为顶部摘要
        active_matrix = matrices[0] if matrices else {'columns': []}
        total_changed = 0
        total_prod_count = 0
        for g_idx in range(len(active_matrix.get('columns', []))):
            col = active_matrix['columns'][g_idx]
            total_prod_count += int(col.get('count', 0) or 0)
            if t_idx is not None and positions is not None and t_idx < positions.shape[0] and g_idx < positions.shape[1]:
                cur_pos = positions[t_idx, g_idx]
                prev_pos = positions[prev_t_idx, g_idx] if prev_t_idx is not None and prev_t_idx < positions.shape[0] else None
                current_active = int(np.sum(np.abs(cur_pos) > 1e-12))
                prev_active = int(np.sum(np.abs(prev_pos) > 1e-12)) if prev_pos is not None else 0
                total_changed += abs(current_active - prev_active)
        avg_turnover = total_changed / max(total_prod_count, 1) * 100.0 if total_prod_count > 0 else 0.0

        # 所有时间点（epoch 毫秒），用于前/后导航
        all_timestamps_ms = sorted(set(
            int(ts_epoch * 1000) for ts_epoch, _idx in all_times
        ))
        # 用最接近的 all_timestamps_ms 条目（而非前端传来的不精确 timestamp_ms）
        closest_ms = min(all_timestamps_ms, key=lambda x: abs(x - int(timestamp_ms)))
        current_index = all_timestamps_ms.index(closest_ms)
        change_indices = _snapshot_change_indices(group_result)
        change_timestamps_ms = [
            int(time_epochs[idx] * 1000)
            for idx in change_indices
            if 0 <= idx < len(time_epochs)
        ]
        prev_change_ms = None
        next_change_ms = None
        for change_ms in change_timestamps_ms:
            if change_ms < closest_ms:
                prev_change_ms = change_ms
            elif change_ms > closest_ms and next_change_ms is None:
                next_change_ms = change_ms

        # ── 附加元信息供前端按稳定 group_id 分层渲染 ──
        _raw_group_names = getattr(group_result, 'group_names', None) or {}
        snapshot_group_names = {}
        for k, v in _raw_group_names.items():
            try:
                snapshot_group_names[int(k)] = str(v)
            except (TypeError, ValueError):
                snapshot_group_names[str(k)] = str(v)

        return jsonify({
            'success': True,
            'matrices': matrices,
            'default_matrix_key': 'raw',
            'timestamp_ms': closest_ms,
            'has_prev': prev_entry is not None,
            'has_next': current_index >= 0 and current_index < len(all_timestamps_ms) - 1,
            'all_timestamps_ms': all_timestamps_ms,
            'display_timezone': display_timezone,
            'change_timestamps_ms': change_timestamps_ms,
            'prev_change_timestamp_ms': prev_change_ms,
            'next_change_timestamp_ms': next_change_ms,
            'has_prev_change': prev_change_ms is not None,
            'has_next_change': next_change_ms is not None,
            'group_names': snapshot_group_names,
            'capital_warning': capital_diagnostics['warning'] if capital_diagnostics else None,
            'capital_diagnostics': capital_diagnostics,
            'summary': {
                'avg_turnover': round(avg_turnover, 1),
                'total_changed': int(total_changed),
                'total_prod_count': int(total_prod_count),
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_group_order_flow', methods=['POST'])
def get_group_order_flow():
    """Return order lifecycle trace for one group from the latest event run."""
    data = request.get_json() or {}
    page_uuid = str(data.get('page_uuid') or '')
    try:
        if page_uuid and not _request_has_group_job_selector(data) and runtime_state.get_page_owner(page_uuid) != current_user():
            return jsonify({'success': False, 'error': 'page_uuid 不属于当前用户'}), 403
        event_execution = _group_execution_for_request(data)
        if not event_execution:
            return jsonify({'success': False, 'error': '当前页面尚无事件回测结果，请先运行分组测试'}), 400
        return jsonify(_event_order_flow_detail(
            event_execution,
            group_id=str(data.get('group_id') or '') or None,
            product_path_selection_id=str(data.get('product_path_selection_id') or '') or None,
            group_index=data.get('group_index'),
            timestamp_ms=data.get('timestamp_ms'),
            order_id=str(data.get('order_id') or '') or None,
        ))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


def _owner_strategy_id(owner: dict[str, Any]) -> str:
    """Return the canonical strategy identity at the group API boundary."""
    return str(owner.get("strategy_id") or owner.get("group_id") or "")


def _owner_display_name(owner: dict[str, Any]) -> str:
    """Return the canonical display label, with historical read fallback."""
    return str(
        owner.get("display_name")
        or owner.get("group_name")
        or _owner_strategy_id(owner)
        or ""
    )


def _event_group_snapshot(
    execution: dict,
    product_path_selection_id: str,
    timestamp_ms: int,
    event_cursor: str | None = None,
) -> dict:
    engine_result = execution.get("engine_result") or {}
    portfolios = engine_result.get("portfolios") or {}
    owners = [
        owner for owner in execution.get("group_owner") or []
        if str(owner.get("product_path_selection_id") or "") == product_path_selection_id
    ]
    if not owners:
        raise ValueError("当前页面最近一次事件回测不包含该 product_path_selection_id")
    first = portfolios.get(_owner_strategy_id(owners[0])) or {}
    first_curve = first.get("position_curve") or {}
    if not first_curve:
        raise ValueError("所选回测框架没有返回逐事件持仓快照")
    timestamps = sorted(pd.Timestamp(value) for value in first_curve)
    target = pd.Timestamp(timestamp_ms, unit="ms", tz="UTC")
    if timestamps[0].tzinfo is None:
        target = target.tz_localize(None)
    timestamp_index = min(
        range(len(timestamps)), key=lambda index: abs(timestamps[index] - target)
    )
    events = []
    latest_targets = {_owner_strategy_id(owner): {} for owner in owners}
    previous_positions = None
    traces = engine_result.get("target_trace") or {}
    for timestamp in timestamps:
        timestamp_positions = {
            _owner_strategy_id(owner): (
                portfolios[_owner_strategy_id(owner)]
                .get("position_curve", {})
                .get(timestamp.isoformat(), {})
            )
            for owner in owners
        }
        target_changed = False
        for strategy_id in latest_targets:
            exact = (traces.get(strategy_id) or {}).get(timestamp.isoformat())
            if exact is not None:
                latest_targets[strategy_id] = exact
                target_changed = True
        event_types = []
        if target_changed:
            event_types.append("TARGET")
        if previous_positions is not None and timestamp_positions != previous_positions:
            event_types.append("FILL")
        event_types.append("BAR_CLOSE")
        timestamp_ms_value = int(timestamp.timestamp() * 1000)
        for sequence, event_type in enumerate(event_types):
            event_positions = (
                previous_positions
                if event_type == "TARGET" and previous_positions is not None
                else timestamp_positions
            )
            events.append({
                "cursor": f"{timestamp_ms_value}:{sequence}",
                "timestamp": timestamp,
                "event_type": event_type,
                "positions": event_positions,
                "targets": {key: dict(value) for key, value in latest_targets.items()},
            })
        previous_positions = timestamp_positions
    if event_cursor:
        matching = [index for index, event in enumerate(events) if event["cursor"] == event_cursor]
        if not matching:
            raise ValueError("事件快照 cursor 已过期，请重新点击图表")
        event_index = matching[0]
    else:
        target_timestamp = timestamps[timestamp_index]
        matching = [
            index for index, event in enumerate(events)
            if event["timestamp"] == target_timestamp
        ]
        # A chart click represents the bar timestamp, not a specific internal
        # event. Prefer the actionable ledger state for that timestamp so the
        # snapshot explains what changed, instead of defaulting to BAR_CLOSE
        # where positions are usually unchanged from the immediately preceding
        # fill event.
        event_index = next(
            (
                index for index in matching
                if events[index]["event_type"] in {"FILL", "REJECT"}
            ),
            next(
                (index for index in matching if events[index]["event_type"] == "TARGET"),
                matching[-1],
            ),
        )
    selected_event = events[event_index]
    previous_event = events[event_index - 1] if event_index > 0 else None
    current = selected_event["timestamp"]
    instruments = sorted({
        instrument
        for owner in owners
        for positions in (portfolios.get(_owner_strategy_id(owner), {}).get("position_curve") or {}).values()
        for instrument in positions
    })

    def _instrument_parent_name(instrument: str) -> str:
        product = resolve_term_structure_product(instrument)
        if product is None:
            product = _cn_futures_contract_parent(instrument)
        return str(getattr(product, "name", None) or instrument)

    def _position_status(quantity: float, old_quantity: float) -> str:
        delta = quantity - old_quantity
        if abs(old_quantity) <= 1e-12 and abs(quantity) > 1e-12:
            return "entering"
        if abs(old_quantity) > 1e-12 and abs(quantity) <= 1e-12:
            return "exiting"
        if abs(quantity) > abs(old_quantity) + 1e-12:
            return "increasing"
        if abs(quantity) + 1e-12 < abs(old_quantity):
            return "decreasing"
        if abs(quantity) > 1e-12:
            return "holding"
        return "absent"

    def _position_cell(instrument: str, quantity: float, old_quantity: float) -> dict[str, Any]:
        delta = quantity - old_quantity
        return {
            "status": _position_status(quantity, old_quantity),
            "product": _snapshot_product_display(instrument),
            "quantity": quantity,
            "previous_quantity": old_quantity,
            "delta_quantity": delta,
            "change_direction": "increase" if delta > 0 else "decrease" if delta < 0 else "flat",
            "currency": "CNY",
        }

    def _target_cell(instrument: str, weight: float) -> dict[str, Any]:
        return {
            "status": "selected" if abs(weight) > 1e-12 else "absent",
            "product": _snapshot_product_display(instrument),
            "selected": abs(weight) > 1e-12,
            "open_reason": f"目标权重 {weight:.4%}" if abs(weight) > 1e-12 else None,
            "currency": "CNY",
        }

    def _collapse_names(names: list[str]) -> list[str]:
        return sorted({_instrument_parent_name(name) for name in names})

    def _aggregate_position_maps(values: dict[str, float]) -> dict[str, float]:
        collapsed: dict[str, float] = {}
        for instrument, value in values.items():
            parent = _instrument_parent_name(instrument)
            collapsed[parent] = collapsed.get(parent, 0.0) + float(value)
        return collapsed

    def _previous_event_values_from_current_curve(
        current_values: dict[str, float],
        current_positions: dict[str, float],
        previous_positions: dict[str, float],
        *,
        absolute: bool = False,
    ) -> dict[str, float]:
        previous_values: dict[str, float] = {}
        for instrument, current_value in current_values.items():
            quantity = float(current_positions.get(instrument, 0.0))
            previous_quantity = float(previous_positions.get(instrument, 0.0))
            if abs(quantity) <= 1e-12:
                previous_values[instrument] = 0.0
                continue
            if absolute:
                previous_values[instrument] = abs(previous_quantity) * (abs(float(current_value)) / abs(quantity))
            else:
                previous_values[instrument] = previous_quantity * (float(current_value) / quantity)
        for instrument, previous_quantity in previous_positions.items():
            if instrument not in previous_values and abs(float(previous_quantity)) > 1e-12:
                previous_values[instrument] = 0.0
        return previous_values

    def _build_position_matrix(
        key: str,
        label: str,
        names: list[str],
        *,
        collapse_products: bool = False,
    ) -> tuple[dict[str, Any], int]:
        rows = _collapse_names(names) if collapse_products else names
        matrix_columns = []
        matrix_cells = [[] for _ in rows]
        total_row = []
        cash_row = []
        changed_count = 0
        for owner in owners:
            strategy_id = _owner_strategy_id(owner)
            portfolio = portfolios[strategy_id]
            now = selected_event["positions"].get(strategy_id, {})
            before = (
                previous_event["positions"].get(strategy_id, {})
                if previous_event is not None else {}
            )
            current_notional = (
                (portfolio.get("notional_curve") or {}).get(selected_event["timestamp"].isoformat(), {})
            )
            previous_notional = (
                (portfolio.get("notional_curve") or {}).get(previous_event["timestamp"].isoformat(), {})
                if previous_event is not None else {}
            )
            current_margin = (
                (portfolio.get("margin_curve") or {}).get(selected_event["timestamp"].isoformat(), {})
            )
            previous_margin = (
                (portfolio.get("margin_curve") or {}).get(previous_event["timestamp"].isoformat(), {})
                if previous_event is not None else {}
            )
            if previous_event is not None and previous_event["timestamp"] == selected_event["timestamp"]:
                previous_notional = _previous_event_values_from_current_curve(
                    current_notional, now, before
                )
                previous_margin = _previous_event_values_from_current_curve(
                    current_margin, now, before, absolute=True
                )
            if collapse_products:
                now_values = _aggregate_position_maps(now)
                before_values = _aggregate_position_maps(before)
                current_notional_values = _aggregate_position_maps(current_notional)
                previous_notional_values = _aggregate_position_maps(previous_notional)
                current_margin_values = _aggregate_position_maps(current_margin)
                previous_margin_values = _aggregate_position_maps(previous_margin)
            else:
                now_values = {name: float(now.get(name, 0.0)) for name in rows}
                before_values = {name: float(before.get(name, 0.0)) for name in rows}
                current_notional_values = {name: float(current_notional.get(name, 0.0)) for name in rows}
                previous_notional_values = {name: float(previous_notional.get(name, 0.0)) for name in rows}
                current_margin_values = {name: float(current_margin.get(name, 0.0)) for name in rows}
                previous_margin_values = {name: float(previous_margin.get(name, 0.0)) for name in rows}
            active_count = sum(abs(float(value)) > 1e-12 for value in now_values.values())
            column_events = []
            if selected_event["event_type"] == "TARGET":
                if selected_event["targets"].get(strategy_id):
                    column_events.append({"type": "TARGET", "label": "目标更新"})
            elif selected_event["event_type"] in {"FILL", "REJECT"}:
                changed_here = any(
                    abs(float(now_values.get(row_name, 0.0)) - float(before_values.get(row_name, 0.0))) > 1e-12
                    for row_name in rows
                )
                column_events.append({
                    "type": selected_event["event_type"],
                    "label": "成交后" if changed_here else "无成交",
                })
            else:
                column_events.append({"type": selected_event["event_type"], "label": "收盘持有"})
            matrix_columns.append({
                "label": _owner_display_name(owner),
                "count": active_count,
                "events": column_events,
            })
            equity_curve = portfolio.get("equity_curve") or {}
            equity_now = float(equity_curve.get(selected_event["timestamp"].isoformat(), 0.0) or 0.0)
            equity_before = (
                float(equity_curve.get(previous_event["timestamp"].isoformat(), equity_now) or equity_now)
                if previous_event is not None else equity_now
            )
            margin_now = sum(float(value) for value in current_margin_values.values()) if current_margin else 0.0
            margin_before = sum(float(value) for value in previous_margin_values.values()) if previous_margin else 0.0
            notional_now = sum(float(value) for value in current_notional_values.values())
            notional_before = sum(float(value) for value in previous_notional_values.values())
            cash_now = equity_now - margin_now if current_margin else equity_now - notional_now
            cash_before = equity_before - margin_before if current_margin else equity_before - notional_before
            total_row.append({
                "status": "increasing" if equity_now > equity_before + 1e-12 else "decreasing" if equity_now + 1e-12 < equity_before else "holding",
                "product": {"name": "总资产"},
                "currency": "CNY",
                "quantity": None,
                "amount": round(equity_now, 2),
                "previous_amount": round(equity_before, 2),
                "delta_amount": round(equity_now - equity_before, 2),
                "margin_amount": round(margin_now, 2) if current_margin else None,
                "previous_margin_amount": round(margin_before, 2) if current_margin else None,
                "delta_margin_amount": round(margin_now - margin_before, 2) if current_margin else None,
                "change_direction": "increase" if equity_now > equity_before + 1e-12 else "decrease" if equity_now + 1e-12 < equity_before else "flat",
            })
            cash_row.append({
                "status": "increasing" if cash_now > cash_before + 1e-12 else "decreasing" if cash_now + 1e-12 < cash_before else "holding",
                "product": {"name": "现金"},
                "currency": "CNY",
                "quantity": None,
                "amount": round(cash_now, 2),
                "previous_amount": round(cash_before, 2),
                "delta_amount": round(cash_now - cash_before, 2),
                "change_direction": "increase" if cash_now > cash_before + 1e-12 else "decrease" if cash_now + 1e-12 < cash_before else "flat",
            })
            for row, instrument in enumerate(rows):
                quantity = float(now_values.get(instrument, 0.0))
                old_quantity = float(before_values.get(instrument, 0.0))
                delta = quantity - old_quantity
                if abs(delta) > 1e-12:
                    changed_count += 1
                cell = _position_cell(instrument, quantity, old_quantity)
                notional = float(current_notional_values.get(instrument, 0.0))
                old_notional = float(previous_notional_values.get(instrument, 0.0))
                cell["amount"] = round(notional, 2)
                cell["previous_amount"] = round(old_notional, 2)
                cell["delta_amount"] = round(notional - old_notional, 2)
                if current_margin:
                    margin = float(current_margin_values.get(instrument, 0.0))
                    old_margin = float(previous_margin_values.get(instrument, 0.0))
                    cell["margin_amount"] = round(margin, 2)
                    cell["previous_margin_amount"] = round(old_margin, 2)
                    cell["delta_margin_amount"] = round(margin - old_margin, 2)
                matrix_cells[row].append(cell)
        return {
            "key": key,
            "label": label,
            "columns": matrix_columns,
            "rows": [{"name": "总资产"}, {"name": "现金"}] + [
                _snapshot_product_display(instrument) for instrument in rows
            ],
            "cells": [total_row, cash_row] + matrix_cells,
        }, changed_count

    def _build_target_matrix(
        key: str,
        label: str,
        names: list[str],
        *,
        collapse_products: bool = False,
    ) -> dict[str, Any]:
        rows = _collapse_names(names) if collapse_products else names
        matrix_columns = []
        matrix_cells = [[] for _ in rows]
        for owner in owners:
            strategy_id = _owner_strategy_id(owner)
            weights = selected_event["targets"].get(strategy_id, {})
            if collapse_products:
                weight_values: dict[str, float] = {}
                for instrument, weight in weights.items():
                    parent = _instrument_parent_name(instrument)
                    weight_values[parent] = weight_values.get(parent, 0.0) + float(weight)
            else:
                weight_values = {name: float(weights.get(name, 0.0)) for name in rows}
            selected_count = sum(abs(float(value)) > 1e-12 for value in weight_values.values())
            matrix_columns.append({
                "label": _owner_display_name(owner),
                "count": selected_count,
            })
            for row, instrument in enumerate(rows):
                matrix_cells[row].append(_target_cell(instrument, float(weight_values.get(instrument, 0.0))))
        return {
            "key": key,
            "label": label,
            "columns": matrix_columns,
            "rows": [_snapshot_product_display(instrument) for instrument in rows],
            "cells": matrix_cells,
        }

    positions_contracts, total_changed = _build_position_matrix(
        "positions_contracts", "实际持仓 · 合约", instruments, collapse_products=False
    )
    positions_products, _ = _build_position_matrix(
        "positions_products", "实际持仓 · 品种", instruments, collapse_products=True
    )
    targets_contracts = _build_target_matrix(
        "targets_contracts", "策略目标 · 合约", instruments, collapse_products=False
    )
    targets_products = _build_target_matrix(
        "targets_products", "策略目标 · 品种", instruments, collapse_products=True
    )
    all_ms = [int(timestamp.timestamp() * 1000) for timestamp in timestamps]
    change_indices = [
        index for index, event in enumerate(events) if event["event_type"] in {"FILL", "REJECT"}
    ]
    previous_change = next(
        (events[index] for index in reversed(change_indices) if index < event_index), None
    )
    next_change = next(
        (events[index] for index in change_indices if index > event_index), None
    )
    return {
        "success": True,
        "run_id": execution.get("run_id"),
        "engine": engine_result.get("engine"),
        "matrices": [
            positions_contracts,
            positions_products,
            targets_contracts,
            targets_products,
        ],
        "default_matrix_key": "positions_contracts",
        "timestamp_ms": int(current.timestamp() * 1000),
        "event_cursor": selected_event["cursor"],
        "event_type": selected_event["event_type"],
        "event_label": {
            "TARGET": "策略目标更新",
            "FILL": "成交后账本",
            "REJECT": "订单拒绝",
            "BAR_CLOSE": "时间片收盘",
        }[selected_event["event_type"]],
        "event_cursors": [event["cursor"] for event in events],
        "order_flow_groups": [
            {
                "group_id": _owner_strategy_id(owner),
                "group_name": _owner_display_name(owner),
            }
            for owner in owners
        ],
        "all_timestamps_ms": all_ms,
        "has_prev": event_index > 0,
        "has_next": event_index + 1 < len(events),
        "prev_change_timestamp_ms": (
            int(previous_change["timestamp"].timestamp() * 1000) if previous_change else None
        ),
        "next_change_timestamp_ms": (
            int(next_change["timestamp"].timestamp() * 1000) if next_change else None
        ),
        "prev_change_event_cursor": previous_change["cursor"] if previous_change else None,
        "next_change_event_cursor": next_change["cursor"] if next_change else None,
        "summary": {
            "avg_turnover": 0.0,
            "total_changed": total_changed,
            "total_prod_count": sum(column["count"] for column in positions_contracts["columns"]),
        },
    }


def _event_order_flow_detail(
    execution: dict,
    *,
    group_id: str | None = None,
    product_path_selection_id: str | None = None,
    group_index: Any = None,
    timestamp_ms: Any = None,
    order_id: str | None = None,
) -> dict[str, Any]:
    owners = _event_order_flow_owners(
        execution,
        group_id=group_id,
        product_path_selection_id=product_path_selection_id,
        group_index=group_index,
    )
    engine_result = execution.get("engine_result") or {}
    portfolios = engine_result.get("portfolios") or {}
    target_timestamp = _timestamp_from_epoch_ms(timestamp_ms)
    groups = []
    for owner in owners:
        strategy_id = _owner_strategy_id(owner)
        portfolio = portfolios.get(strategy_id) or {}
        records = list(portfolio.get("execution_trace") or [])
        if order_id:
            records = [row for row in records if str(row.get("order_id") or "") == order_id]
        if target_timestamp is not None:
            records = [
                row for row in records
                if _same_epoch_millisecond(row.get("timestamp"), target_timestamp)
            ]
        records = sorted(
            records,
            key=lambda row: (
                str(row.get("timestamp") or ""),
                str(row.get("order_id") or ""),
                str(row.get("step") or ""),
            ),
        )
        groups.append({
            "group_id": strategy_id,
            "group_name": _owner_display_name(owner),
            "records": records,
        })
    return {
        "success": True,
        "groups": groups,
        "record_count": sum(len(group["records"]) for group in groups),
    }


def _event_order_flow_owners(
    execution: dict,
    *,
    group_id: str | None,
    product_path_selection_id: str | None,
    group_index: Any,
) -> list[dict[str, Any]]:
    owners = [
        owner for owner in execution.get("group_owner") or []
        if not owner.get("is_ls")
    ]
    if group_id:
        owners = [owner for owner in owners if _owner_strategy_id(owner) == group_id]
    elif product_path_selection_id:
        owners = [
            owner for owner in owners
            if str(owner.get("product_path_selection_id") or "") == product_path_selection_id
        ]
        if group_index is not None:
            index = int(group_index)
            owners = [owner for owner in owners if int(owner.get("group_index") or 0) == index]
    if len(owners) != 1:
        raise ValueError(
            f"事件回测中无法唯一定位订单流水：group_id={group_id or ''}, "
            f"product_path_selection_id={product_path_selection_id or ''}, "
            f"group_index={group_index}, matches={len(owners)}"
        )
    return owners


def _timestamp_from_epoch_ms(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    timestamp = cast(pd.Timestamp, pd.Timestamp(int(value), unit="ms", tz="UTC"))
    if pd.isna(timestamp):
        return None
    return timestamp


def _same_epoch_millisecond(value: Any, target: pd.Timestamp) -> bool:
    if value is None:
        return False
    current = cast(pd.Timestamp, pd.Timestamp(value))
    if pd.isna(current):
        return False
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    return int(current.timestamp() * 1000) == int(target.timestamp() * 1000)


def _event_group_detail(
    execution: dict,
    product_path_selection_id: str,
    group_index: int,
    *,
    group_id: str | None = None,
) -> dict:
    if group_id:
        owners = [
            owner for owner in execution.get("group_owner") or []
            if _owner_strategy_id(owner) == group_id
            and not owner.get("is_ls")
        ]
    else:
        owners = [
            owner for owner in execution.get("group_owner") or []
            if str(owner.get("product_path_selection_id") or "") == product_path_selection_id
            and not owner.get("is_ls")
            and int(owner.get("group_index") or 0) == group_index
        ]
    if len(owners) != 1:
        raise ValueError(
            f"事件回测中无法唯一定位分组：group_id={group_id or ''}, "
            f"product_path_selection_id={product_path_selection_id}, "
            f"group_index={group_index}, matches={len(owners)}"
        )
    owner = owners[0]
    strategy_id = _owner_strategy_id(owner)
    engine_result = execution.get("engine_result") or {}
    portfolio = (engine_result.get("portfolios") or {}).get(strategy_id) or {}
    curve = portfolio.get("equity_curve") or {}
    position_curve = portfolio.get("position_curve") or {}
    if not curve or not position_curve:
        raise ValueError("所选回测框架没有返回逐事件净值与持仓曲线")

    index = [pd.Timestamp(value) for value in curve]
    equity = pd.Series([float(value) for value in curve.values()], index=index)
    returns = equity.pct_change().fillna(0.0).to_numpy().reshape(-1, 1)
    products_by_group = {0: {}}
    for timestamp in index:
        positions = position_curve.get(timestamp.isoformat(), {})
        products_by_group[0][timestamp] = [
            instrument for instrument, quantity in positions.items()
            if abs(float(quantity)) > 1e-12
        ]
    serialized = execution.get("serialized_execution") or {}
    detail_context = execution.get("detail_context") or {}
    payload = execution.get("payload") or detail_context.get("payload") or {}
    strategy_settings = (
        execution.get("settings_by_strategy")
        or detail_context.get("settings_by_strategy")
        or {}
    ).get(strategy_id) or {}
    display_name = _owner_display_name(owner)
    serialized_group = next(
        (
            group for group in serialized.get("groups") or ()
            if str(group.get("group_id") or "") == strategy_id
        ),
        {},
    )
    metrics_key = str(
        serialized_group.get("metrics_key") or strategy_id or display_name
    )
    serialized_metrics = serialized.get("metrics") or {}
    summary = (
        serialized_metrics.get(metrics_key)
        or serialized_metrics.get(display_name)
        or {}
    )
    detail = build_group_detail(
        0,
        products_by_group,
        returns,
        index,
        summary,
    )
    detail["product_analysis"] = _event_product_analysis(portfolio, payload, strategy_settings)
    return detail


def _event_group_ranking_detail(
    execution: dict,
    product_path_selection_id: str,
    strategy_configuration_id: str = "",
) -> dict:
    owners = sorted(
        (
            owner for owner in execution.get("group_owner") or []
            if str(owner.get("product_path_selection_id") or "") == product_path_selection_id
            and (
                not strategy_configuration_id
                or str(owner.get("strategy_configuration_id") or "")
                == strategy_configuration_id
            )
            and not owner.get("is_ls")
        ),
        key=lambda owner: int(owner.get("group_index") or 0),
    )
    if len(owners) < 2:
        raise ValueError("事件回测中至少需要两个普通分组才能分析排序能力")
    portfolios = (execution.get("engine_result") or {}).get("portfolios") or {}
    series = []
    for owner in owners:
        strategy_id = _owner_strategy_id(owner)
        portfolio = portfolios.get(strategy_id) or {}
        curve = portfolio.get("display_equity_curve") or portfolio.get("equity_curve") or {}
        if not curve:
            raise ValueError(f"分组 {strategy_id} 没有返回净值曲线")
        equity = pd.Series(
            [float(value) for value in curve.values()],
            index=pd.DatetimeIndex([pd.Timestamp(value) for value in curve]),
        )
        series.append(equity.pct_change().fillna(0.0).rename(strategy_id))
    aligned = pd.concat(series, axis=1, join="inner").sort_index()
    return build_group_ranking_detail(aligned.to_numpy(), list(aligned.index))


@sft_bp.route('/get_group_detail', methods=['POST'])
def get_group_detail():
    """Return first-phase detail analytics for one group from the latest run."""
    data = request.get_json() or {}
    product_path_selection_id = data.get('product_path_selection_id')
    group_index = data.get('group_index')
    page_uuid = str(data.get('page_uuid') or '')
    if product_path_selection_id is None or group_index is None:
        return jsonify({'success': False, 'error': '缺少 product_path_selection_id 或 group_index'}), 400
    try:
        group_index = int(group_index)
        if page_uuid and not _request_has_group_job_selector(data) and runtime_state.get_page_owner(page_uuid) != current_user():
            return jsonify({'success': False, 'error': 'page_uuid 不属于当前用户'}), 403
        retained_analysis = _strategy_analysis_for_request(data)
        if retained_analysis:
            return jsonify({
                'success': True,
                'detail': _retained_strategy_detail(
                    retained_analysis, data, group_index,
                ),
            })
        event_execution = _group_execution_for_request(data)
        if not event_execution:
            return jsonify({'success': False, 'error': '当前页面尚无事件回测结果，请先运行分组测试'}), 400
        return jsonify({
            'success': True,
            'detail': _event_group_detail(
                event_execution,
                str(product_path_selection_id),
                group_index,
                group_id=str(data.get('group_id') or '') or None,
            ),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})



@sft_bp.route('/get_group_ranking_detail', methods=['POST'])
def get_group_ranking_detail():
    """Return second-phase whole-test ranking analytics from the latest run."""
    data = request.get_json() or {}
    product_path_selection_id = data.get('product_path_selection_id')
    strategy_configuration_id = str(
        data.get('strategy_configuration_id') or ''
    )
    page_uuid = str(data.get('page_uuid') or '')
    if product_path_selection_id is None:
        return jsonify({'success': False, 'error': '缺少 product_path_selection_id'}), 400
    try:
        if page_uuid and not _request_has_group_job_selector(data) and runtime_state.get_page_owner(page_uuid) != current_user():
            return jsonify({'success': False, 'error': 'page_uuid 不属于当前用户'}), 403
        retained_analysis = _strategy_analysis_for_request(data)
        if retained_analysis:
            key = "|".join((
                str(product_path_selection_id), strategy_configuration_id,
            ))
            return jsonify({
                'success': True,
                'detail': _event_group_ranking_detail(
                    _strategy_analysis_execution(retained_analysis),
                    str(product_path_selection_id),
                    strategy_configuration_id,
                ),
            })
        event_execution = _group_execution_for_request(data)
        if not event_execution:
            return jsonify({'success': False, 'error': '当前页面尚无事件回测结果，请先运行分组测试'}), 400
        return jsonify({
            'success': True,
            'detail': _event_group_ranking_detail(
                event_execution,
                str(product_path_selection_id),
                strategy_configuration_id,
            ),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_product_path_selection_session_info', methods=['POST'])
def get_product_path_selection_session_info():
    """返回产品路径选择运行摘要信息（供第3层策略通知表格使用）。

    请求：{product_path_selection_ids: [str, ...]}

    返回：{
        product_path_selections: [{
            product_path_selection_id, runtime_context_alias, product_count,
            factors: [{
                alias, name, freq,
                n_groups: int,   // 上次分组测试用的组数
                rebalance_trigger, position_policy,
                has_results: bool,
            }]
        }]
    }
    """
    data = request.get_json() or {}
    page_uuid = str(data.get('page_uuid') or '')
    if not page_uuid:
        return jsonify({'success': False, 'error': '缺少 page_uuid'}), 400
    if runtime_state.get_page_owner(page_uuid) != current_user():
        return jsonify({'success': False, 'error': 'page_uuid 不属于当前用户'}), 403
    ids = data.get('product_path_selection_ids') or []
    if not ids:
        return jsonify({'success': False, 'error': '缺少 product_path_selection_ids'}), 400

    selections_info = []
    for sid in ids:
        try:
            tester = runtime_state.find_page_object(runtime_state.FACTOR_TESTER, str(sid), allow_suffix=True, page_uuid=page_uuid)
            if tester is None:
                selections_info.append({'product_path_selection_id': str(sid), 'error': '未找到运行上下文'})
                continue
            factors_info = []
            for f in (getattr(tester, 'factors', None) or []):
                info = {
                    'alias': getattr(f, 'alias', None) or getattr(f, 'name', '?'),
                    'name': getattr(f, 'name', '?'),
                    'freq': f.freq.name if hasattr(f, 'freq') and f.freq else None,
                }
                # 如果该因子有上次分组测试的结果
                result = tester.results.get(f) if hasattr(tester, 'results') else None
                if result is not None and result.group_result is not None:
                    gr = result.group_result
                    info['n_groups'] = gr.returns_np.shape[1] if hasattr(gr, 'returns_np') and gr.returns_np is not None else None
                    trigger = getattr(gr, 'rebalance_trigger', None)
                    policy = getattr(gr, 'position_policy', None)
                    if trigger is not None:
                        info['rebalance_trigger'] = trigger
                    if policy is not None:
                        info['position_policy'] = policy
                    info['has_results'] = True
                else:
                    info['has_results'] = False
                factors_info.append(info)
            selections_info.append({
                'product_path_selection_id': str(sid),
                'runtime_context_alias': getattr(tester, 'alias', '?'),
                'product_count': len(tester.products) if hasattr(tester, 'products') else 0,
                'factors': factors_info,
            })
        except Exception as e:
            selections_info.append({'product_path_selection_id': str(sid), 'error': str(e)})

    return jsonify({'success': True, 'product_path_selections': selections_info})
