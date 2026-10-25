"""Derive the catalog staging requests frozen into one Nautilus RunSpec."""

from __future__ import annotations

from typing import Any


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
        entry["paths"] = sorted(set(entry["paths"]) | {str(path) for path in paths})
        strategy_id = str(group.get("id") or "").strip()
        if strategy_id:
            entry["strategy_ids"] = sorted(set(entry["strategy_ids"]) | {strategy_id})
    return [by_scope[key] for key in sorted(by_scope)]
