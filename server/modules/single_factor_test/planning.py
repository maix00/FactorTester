"""Production planning for immutable single-factor-family research jobs."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson
import pandas as pd


def _timestamp_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    ts = getattr(value, "ts", value)
    return "" if ts is None else pd.Timestamp(ts).isoformat()


def _name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _backtest_plan(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from server.modules.single_factor_test.group import prepare_group_run_spec
    from tools.testers.backtest.modules.engine import engine_mode_for
    from tools.testers.backtest.modules.market_data import (
        _MISSING_DATA_SOURCE,
        _data_source_instance_label,
        _factor_required_columns,
        _product_available_freqs,
        _required_data_source_for_strategy,
        _required_frequency_for_strategy,
        _select_required_product_frequency,
        _select_required_product_source,
    )
    from tools.testers.backtest.modules.term_structure import _expand_product_contracts

    prepared = prepare_group_run_spec(data)
    start_text = _timestamp_text(prepared["start_dt"])
    end_text = _timestamp_text(prepared["end_dt"])
    start_date = start_text[:10] or None
    end_date = end_text[:10] or None
    requirements: dict[str, dict[str, Any]] = {}
    strategies: dict[str, dict[str, Any]] = {}
    notices: list[dict[str, Any]] = []
    for strategy_id, config in prepared["resolved_settings_by_alias"].items():
        selection = config.get("product_path_selection")
        products = list(getattr(selection, "products", ()) or ())
        required_frequency = _required_frequency_for_strategy(config, products)
        required_sources = _required_data_source_for_strategy(config)
        factor_columns = list(_factor_required_columns(config.get("factor")))
        engine_mode = engine_mode_for(config)
        strategy_products: list[str] = []
        strategy_contracts: list[str] = []
        for product in products:
            contracts, metadata = _expand_product_contracts(
                product,
                start_date=start_date,
                end_date=end_date,
                engine_mode=engine_mode,
            )
            universe = [product, *[item for item in contracts if item != product]]
            strategy_products.append(_name(product))
            strategy_contracts.extend(_name(item) for item in contracts)
            for row in metadata:
                if not row.get("is_identity") and not any(
                    row.get(key) for key in (
                        "last_trade_date", "expire_date", "delivery_date", "maturity_date",
                        "last_trade_ts", "expire_ts", "delivery_ts", "maturity_ts",
                    )
                ):
                    notices.append({
                        "severity": "warning",
                        "code": "term_structure_lifecycle_authority_missing",
                        "message": "contract lifecycle has no authoritative terminal field",
                        "details": {"contract": str(row.get("contract_product") or row.get("uid") or "")},
                    })
            for item in universe:
                frequency = _select_required_product_frequency(
                    item, _product_available_freqs(item), required_frequency
                )
                if frequency is None:
                    raise ValueError(f"{_name(item)} does not provide required bar frequency")
                source = _select_required_product_source(item, frequency, required_sources)
                if source is _MISSING_DATA_SOURCE:
                    raise ValueError(f"{_name(item)} does not provide the requested data source")
                source_label = _data_source_instance_label(source)
                key = _name(item)
                resolved = {
                    "product": key,
                    "frequency": frequency.name,
                    "data_source": source_label,
                    "factor_columns": factor_columns,
                    "start": start_text,
                    "end": end_text,
                }
                existing = requirements.get(key)
                if existing is not None and existing != resolved:
                    raise ValueError(f"conflicting market data requirements for {key}")
                requirements[key] = resolved
        strategies[str(strategy_id)] = {
            "selection_id": str(getattr(selection, "selection_id", "")),
            "products": sorted(set(strategy_products)),
            "contracts": sorted(set(strategy_contracts)),
            "frequency": required_frequency.name,
            "requested_sources": list(required_sources),
            "factor_columns": factor_columns,
            "engine_mode": engine_mode,
        }
    resolved = {
        "kind": "backtest",
        "run_window": {"start": start_text, "end": end_text},
        "strategies": strategies,
        "data_requirements": [requirements[key] for key in sorted(requirements)],
    }
    return resolved, notices


def _analysis_plan(kind: str, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from server.modules.shared.factor_tester_runtime import selection_from_request

    selection = selection_from_request(data, page_uuid="")
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    start = settings.get("start_date") or settings.get("start") or data.get("start_date")
    end = settings.get("end_date") or settings.get("end") or data.get("end_date")
    aliases = [
        str(item.get("alias") or "")
        for item in data.get("factors") or ()
        if isinstance(item, dict) and item.get("alias")
    ]
    single = str(data.get("factor_alias") or data.get("factor_name") or "").strip()
    if single:
        aliases.append(single)
    resolved = {
        "kind": kind,
        "run_window": {
            "start": _timestamp_text(start),
            "end": _timestamp_text(end),
        },
        "selection_id": selection.selection_id,
        "products": sorted(_name(product) for product in selection.products),
        "selected_paths": list(selection.selected_paths),
        "factors": sorted(set(aliases)),
    }
    return resolved, []


def build_execution_plan(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    if kind == "backtest":
        resolved, notices = _backtest_plan(data)
    elif kind in {"ic", "factor_evaluation", "factor_type_analysis"}:
        resolved, notices = _analysis_plan(kind, data)
    else:
        products: set[str] = set(str(item) for item in data.get("products") or ())
        selections = data.get("product_selections") or {}
        values = selections.values() if isinstance(selections, dict) else selections
        if isinstance(values, (list, tuple)) or hasattr(values, "__iter__"):
            for selection in values:
                if not isinstance(selection, dict):
                    continue
                for path in selection.get("selected_paths") or selection.get("paths") or ():
                    if isinstance(path, dict):
                        product = str(path.get("product") or path.get("symbol") or "")
                        if product:
                            products.add(product)
        resolved = {
            "kind": kind,
            "run_window": {
                "start": _timestamp_text(data.get("start_date")),
                "end": _timestamp_text(data.get("end_date")),
            },
            "products": sorted(products),
        }
        notices = []
    resolved_hash = _hash(resolved)
    cache_keys = []
    for item in resolved.get("data_requirements") or ():
        cache_keys.append("|".join((
            str(data.get("_owner") or ""),
            str(item.get("product") or ""),
            str(item.get("data_source") or ""),
            str(item.get("frequency") or ""),
            str(item.get("start") or ""),
            str(item.get("end") or ""),
            ",".join(item.get("factor_columns") or ()),
        )))
    if not cache_keys:
        cache_keys = [
            "|".join((
                str(data.get("_owner") or ""),
                kind,
                product,
                str(resolved.get("run_window") or {}),
            ))
            for product in resolved.get("products") or ()
        ]
    return {
        "plan_version": 1,
        "kind": kind,
        "resolved": resolved,
        "resolved_hash": resolved_hash,
        "cache_keys": sorted(set(cache_keys)),
        "notices": notices,
        "requires_confirmation": any(
            notice.get("severity") == "confirmation_required" for notice in notices
        ),
    }


def verify_execution_plan(kind: str, data: dict[str, Any]) -> None:
    expected = data.get("execution_plan")
    if not isinstance(expected, dict) or not expected.get("resolved_hash"):
        raise ValueError("immutable execution plan is required")
    current = build_execution_plan(kind, data)
    if current["resolved_hash"] != expected["resolved_hash"]:
        raise RuntimeError(
            "execution inputs changed after planning; submit a new job to replan"
        )
