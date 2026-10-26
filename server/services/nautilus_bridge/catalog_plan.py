"""Derive the catalog staging requests frozen into one Nautilus RunSpec."""

from __future__ import annotations

from typing import Any


_EXPANSION_CACHE: dict[tuple[tuple[str, ...], str, str], tuple[str, ...]] = {}
_EXPANSION_CACHE_LIMIT = 64


def _expand_product_paths(paths: list[str], *, start: str, end: str) -> list[str]:
    """Resolve product paths to the contracts listed in the run window.

    A product path is a signal/selection reference, never a tradable
    InstrumentId.  The term-structure/contract catalog decides which listed
    contracts exist for the requested window; those contract UIDs are what
    Nautilus may stage and trade.
    """
    cache_key = (tuple(sorted(set(paths))), start[:10], end[:10])
    cached = _EXPANSION_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    expanded: list[str] = []
    for path in paths:
        marker = "/_products/"
        if marker not in path:
            expanded.append(path)
            continue
        product_name = path.rsplit(marker, 1)[-1]
        try:
            from settings import get_all_products
            from server.modules.shared.price_services import find_product
            product = find_product(get_all_products(), product_name)
        except Exception:
            product = None
        if product is None or not callable(getattr(product, "get_contract_list", None)):
            expanded.append(path)
            continue
        rows = product.get_contract_list(start[:10], end[:10])
        uids = [
            str(row.get("uid")) for row in rows
            if isinstance(row, dict) and row.get("uid")
            and str(row.get("uid")).split("|")[-1].isdigit()
            and int(str(row.get("uid")).split("|")[-1]) >= 1000
        ]
        if not uids:
            expanded.append(path)
            continue
        expanded.extend(uids)
    result = tuple(sorted(set(expanded)))
    if len(_EXPANSION_CACHE) >= _EXPANSION_CACHE_LIMIT:
        _EXPANSION_CACHE.pop(next(iter(_EXPANSION_CACHE)))
    _EXPANSION_CACHE[cache_key] = result
    return list(result)


def catalog_staging_requests(run_spec: dict[str, Any]) -> list[dict[str, Any]]:
    configuration = run_spec.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("Nautilus RunSpec has no configuration")
    shared = configuration.get("shared")
    selections = shared.get("product_selections") if isinstance(shared, dict) else None
    if not isinstance(selections, dict):
        raise ValueError("Nautilus RunSpec has no product selections")
    analyses = configuration.get("analyses") or {}
    backtest = analyses.get("backtest") or {}
    groups = backtest.get("groups") or []
    if not isinstance(groups, list):
        raise ValueError("Nautilus RunSpec backtest groups must be a list")
    by_scope: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Nautilus strategy group must be an object")
        scope = str(
            group.get("product_path_selection_id")
            or group.get("product_scope_ref")
            or ""
        ).strip()
        if not scope:
            raise ValueError("Nautilus strategy group has no product scope")
        selection = selections.get(scope)
        if not isinstance(selection, dict):
            raise ValueError(f"Nautilus product scope is not frozen: {scope}")
        paths = selection.get("paths") or selection.get("selected_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"Nautilus product scope has no frozen paths: {scope}")
        if any(not isinstance(path, str) or not path.strip() for path in paths):
            raise ValueError(f"Nautilus product scope contains an invalid path: {scope}")
        entry = by_scope.setdefault(scope, {"scope_ref": scope, "paths": [], "strategy_ids": []})
        configuration = run_spec.get("configuration") or {}
        analysis = ((configuration.get("analyses") or {}).get("backtest") or {})
        settings = ((analysis.get("execution") or {}).get("settings") or {})
        start = str(
            settings.get("start_date")
            or (configuration.get("analysis") or {}).get("start_date")
            or ""
        )
        end = str(
            settings.get("end_date")
            or (configuration.get("analysis") or {}).get("end_date")
            or ""
        )
        expanded_paths = _expand_product_paths(
            [str(path) for path in paths],
            start=start or "1900-01-01",
            end=end or "2100-01-01",
        )
        entry["paths"] = sorted(set(entry["paths"]) | set(expanded_paths))
        strategy_id = str(group.get("id") or "").strip()
        if strategy_id:
            entry["strategy_ids"] = sorted(set(entry["strategy_ids"]) | {strategy_id})
    return [by_scope[key] for key in sorted(by_scope)]
