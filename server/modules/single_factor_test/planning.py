"""Production planning for immutable single-factor-family research jobs."""

from __future__ import annotations

import hashlib
from copy import deepcopy
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
    """Plan a backtest exclusively from its immutable Nautilus RunSpec.

    Planning must not reopen the authoring editor, expand mutable product
    catalogs, choose another frequency, or import the retired Python engine.
    The RunSpec hash covers the complete product/factor/strategy definitions;
    this compact projection is only the execution cache key and review view.
    """
    from server.services.nautilus_bridge.config import (
        UnsupportedExecutionConfig,
        compile_frozen_execution_plan,
    )
    from server.services.nautilus_bridge.source_registry import (
        UnsupportedNautilusSource,
        from_server_sources,
    )
    from server.services.research_run_identity import (
        NAUTILUS_RUN_SPEC_VERSION,
        hash_run_spec,
    )

    run_spec = data.get("run_spec")
    if not isinstance(run_spec, dict):
        raise ValueError("backtest planning requires a frozen NautilusTrader RunSpec")
    if run_spec.get("run_spec_version") != NAUTILUS_RUN_SPEC_VERSION:
        raise ValueError("legacy backtest RunSpecs are read-only and cannot be planned")
    configuration = run_spec.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("NautilusTrader RunSpec has no frozen configuration")
    analyses = configuration.get("analyses")
    backtest = analyses.get("backtest") if isinstance(analyses, dict) else None
    execution = backtest.get("execution") if isinstance(backtest, dict) else None
    if not isinstance(execution, dict) or (
        execution.get("backend") != "nautilus_trader"
        or execution.get("contract_version") != 4
    ):
        raise ValueError("backtest planning accepts only NautilusTrader contract v4")
    contract = execution.get("nautilus_contract")
    if not isinstance(contract, dict) or contract.get("contract_version") != 2:
        raise ValueError("NautilusTrader RunSpec has no frozen execution contract v2")
    blockers = contract.get("blockers")
    if not isinstance(blockers, list) or blockers:
        first = blockers[0] if isinstance(blockers, list) and blockers else {}
        reason = first.get("reason") if isinstance(first, dict) else None
        raise ValueError("NautilusTrader execution contract is blocked" + (
            f": {reason}" if reason else ""
        ))
    settings = contract.get("settings")
    source = contract.get("source_adapter")
    if not isinstance(settings, dict) or not isinstance(source, dict):
        raise ValueError("NautilusTrader RunSpec is missing its frozen source/settings")

    source_key = str(settings.get("data_source_ref") or "").strip()
    frequency = str(source.get("frequency") or "").strip().upper()
    if not source_key or not frequency:
        raise ValueError("NautilusTrader RunSpec has no frozen source member/frequency")
    try:
        adapter = from_server_sources().adapter_for(
            source_key=source_key,
            frequency=frequency,
            instrument_scope="physical_contract",
        )
    except UnsupportedNautilusSource as exc:
        raise ValueError(str(exc)) from exc
    if (adapter.adapter_id != source.get("adapter_id")
            or adapter.frequency != frequency
            or source.get("feed_kind") != "bar"):
        raise ValueError("frozen Nautilus source adapter differs from the registered adapter")

    # Capability names here are earned by real engine tests and are identical
    # to the capabilities accepted when a ResearchRun is created. Optional
    # volume consumption, daily settlement and historical fees stay blocked
    # until their Job adapters pass their own end-to-end contracts.
    try:
        compiled = compile_frozen_execution_plan(
            settings,
            feed_kind="bar",
            adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )
    except UnsupportedExecutionConfig as exc:
        raise ValueError(f"invalid NautilusTrader execution contract: {exc}") from exc

    shared = configuration.get("shared")
    selections = shared.get("product_selections") if isinstance(shared, dict) else None
    if not isinstance(selections, dict):
        raise ValueError("NautilusTrader RunSpec has no frozen product selections")
    scope_refs = tuple(settings.get("product_scope_refs") or ())
    requirements: list[dict[str, Any]] = []
    for scope_ref in scope_refs:
        selection = selections.get(scope_ref)
        if not isinstance(selection, dict):
            raise ValueError(f"NautilusTrader product scope is not frozen: {scope_ref}")
        paths = selection.get("paths") or selection.get("selected_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"NautilusTrader product scope has no frozen paths: {scope_ref}")
        # This adapter only declares physical contracts. Product-level paths
        # (including continuous main contracts) require a distinct signal
        # stream and roll-aware route; do not reinterpret them as contracts.
        if any(not isinstance(path, str) or not path.strip() for path in paths):
            raise ValueError(f"NautilusTrader product scope contains an invalid path: {scope_ref}")
        requirements.append({
            "product_scope_ref": str(scope_ref),
            "resolution_sha256": str(selection.get("resolution_sha256") or ""),
            "path_count": len(paths),
            "source_member": source_key,
            "adapter_id": adapter.adapter_id,
            "frequency": frequency,
            "start_utc": str(settings["start_utc"]),
            "end_utc": str(settings["end_utc"]),
        })

    backtest_groups = backtest.get("groups") or []
    if not isinstance(backtest_groups, list) or not backtest_groups:
        raise ValueError("NautilusTrader RunSpec has no strategy instances")
    strategies: list[dict[str, Any]] = []
    routes = {
        str(item.get("strategy_id") or ""): item
        for item in settings.get("strategy_venue_bindings") or []
        if isinstance(item, dict)
    }
    for group in backtest_groups:
        if not isinstance(group, dict):
            raise ValueError("NautilusTrader strategy group must be an object")
        strategy_id = str(group.get("id") or "").strip()
        scope_ref = str(
            group.get("product_path_selection_id")
            or group.get("product_scope_ref")
            or ""
        ).strip()
        route = routes.get(strategy_id)
        if not strategy_id or not scope_ref or scope_ref not in scope_refs or route is None:
            raise ValueError("NautilusTrader strategy has no frozen scope/Venue binding")
        strategies.append({
            "strategy_id": strategy_id,
            "product_scope_ref": scope_ref,
            "venue_ids": sorted(str(item).upper() for item in route.get("venue_ids") or []),
        })
    factors = shared.get("factors") or []
    factor_refs = sorted({
        str(item.get("ref") or "")
        for item in factors if isinstance(item, dict) and item.get("ref")
    })
    resolved = {
        "kind": "backtest",
        "run_spec_version": NAUTILUS_RUN_SPEC_VERSION,
        "run_spec_sha256": hash_run_spec(run_spec),
        "execution": compiled.manifest(),
        "source_adapter": {
            "member_key": source_key,
            "adapter_id": adapter.adapter_id,
            "frequency": frequency,
            "instrument_scope": adapter.instrument_scope,
            "clock_policy": adapter.clock_policy,
        },
        "run_window": {
            "start": compiled.start_utc,
            "end": compiled.end_utc,
        },
        "strategies": sorted(strategies, key=lambda item: item["strategy_id"]),
        "factor_refs": factor_refs,
        "data_requirements": sorted(requirements, key=lambda item: item["product_scope_ref"]),
        "external_factor_artifacts": _artifact_plan_rows(data),
    }
    return resolved, []


def _analysis_plan(kind: str, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from server.modules.shared.factor_tester_runtime import selection_from_request

    selection_data = data
    # IC/evaluation payloads historically called this field ``product_paths``
    # while the shared runtime accepts ``selected_paths``/``paths``.  Normalize
    # the immutable request here so capability preflight and the durable
    # planner resolve the same product universe.
    if not any(
        data.get(key) for key in ("product_path_selection", "selected_paths", "paths")
    ):
        product_paths = data.get("product_paths")
        if isinstance(product_paths, list) and product_paths:
            selection_data = {**data, "selected_paths": product_paths}
    selection = selection_from_request(selection_data, page_uuid="")
    execution = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    settings = execution.get("settings") if isinstance(execution.get("settings"), dict) else {}
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
        "external_factor_artifacts": _artifact_plan_rows(data),
        "run_window": {
            "start": _timestamp_text(start),
            "end": _timestamp_text(end),
        },
        "selection_id": selection.selection_id,
        "products": sorted(_name(product) for product in selection.products),
        "selected_paths": list(selection.selected_paths),
        "factors": sorted(set(aliases)),
    }
    if kind == "ic":
        # Keep the submitted rolling contract visible in the immutable plan;
        # resolution to K is factor-specific and is recorded by the worker
        # response after temporal support has been frozen.
        for key in (
            "forward_return_horizons", "ic_lags", "ic_metric_selection",
            "rolling_windows", "rolling_window",
        ):
            if key in data:
                resolved[key] = deepcopy(data[key])
    return resolved, []


def _typed_ic_plan(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Plan the already frozen IC compiler output, without catalog resolution.

    ``typed_ic`` is deliberately the authority at this boundary.  In
    particular, do not call ``selection_from_request`` here: preview and the
    worker must hash the same immutable RunSpec even when the product catalog
    changes between them.
    """
    run_spec = data["run_spec"]
    typed = deepcopy(run_spec["typed_ic"])
    configuration = run_spec.get("configuration") or {}
    shared = configuration.get("shared") or {}
    selections = deepcopy(shared.get("product_selections") or {})
    groups = deepcopy(typed.get("group_provenance") or typed.get("groups") or [])
    products: list[str] = []
    paths: list[Any] = []
    seen_paths: set[str] = set()
    scope_refs = [
        str(group.get("product_scope_ref") or "").strip()
        for group in groups
        if isinstance(group, dict)
    ]
    for scope_ref in scope_refs:
        selection = selections.get(scope_ref) if isinstance(selections, dict) else None
        if not isinstance(selection, dict):
            raise ValueError(f"typed IC scope is not frozen: {scope_ref}")
        for path in selection.get("selected_paths") or selection.get("paths") or ():
            path_key = str(path)
            if path_key not in seen_paths:
                seen_paths.add(path_key)
                paths.append(deepcopy(path))
        products.extend(str(x) for x in selection.get("products") or () if x)
    return {
        "kind": "ic",
        "typed_ic": typed,
        "product_selections": selections,
        "selected_paths": paths,
        "products": sorted(set(products)),
        "group_provenance": groups,
        "external_factor_artifacts": _artifact_plan_rows(data),
    }, []


def _artifact_plan_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    return sorted(
        (
            {
                "artifact_id": str(item.get("artifact_id") or ""),
                "manifest_sha256": str(item.get("manifest_sha256") or ""),
                "factor_sha256": str(item.get("factor_sha256") or ""),
            }
            for item in (data.get("external_factor_artifacts") or [])
            if isinstance(item, dict)
        ),
        key=lambda item: item["artifact_id"],
    )


def build_execution_plan(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    from server.services.factor_revisions import (
        assert_run_spec_factor_revisions_resolvable,
    )

    run_spec = data.get("run_spec")
    if kind in {
        "backtest", "ic", "factor_evaluation", "factor_type_analysis",
    } and isinstance(run_spec, dict):
        assert_run_spec_factor_revisions_resolvable(
            run_spec,
            owner=str(data.get("_owner") or ""),
        )
    if kind == "ic" and isinstance(run_spec, dict) and isinstance(run_spec.get("typed_ic"), dict):
        resolved, notices = _typed_ic_plan(data)
    elif kind == "backtest":
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
