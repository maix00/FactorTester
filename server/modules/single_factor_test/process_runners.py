"""Importable process runners for immutable research RunSpecs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.factors.formula_identity import require_frozen_factor


def _factor_runtime_scope(payload: dict[str, Any]):
    from server.modules.shared.factor_param_resolver import (
        register_factor_param_resolver_for_user,
    )
    from server.services.factor_registry import transient_factor_source_scope

    run_spec = payload.get("run_spec") or {}
    frozen_factors = (run_spec.get("configuration") or {}).get(
        "shared", {},
    ).get("factors") or payload.get("factors") or []
    register_factor_param_resolver_for_user(
        str(payload.get("_owner") or ""), frozen_factors,
    )
    return transient_factor_source_scope(
        str(payload.get("transient_factor_source_scope_id") or ""),
        owner=str(payload.get("_owner") or "").strip(),
    )


def run_group(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    from server.modules.single_factor_test.planning import verify_execution_plan
    from tools.factors.tester_calc.single_factor_test.group.research_run import (
        execute_group_run_spec,
    )

    scope = _factor_runtime_scope(payload)
    with scope:
        verify_execution_plan("backtest", payload)
        execute_group_run_spec(payload, sink=sink, cancel_event=cancel_event)


def _run_analysis(payload: dict[str, Any], sink: Any, cancel_event: Any, *, kind: str) -> None:
    from server.modules.single_factor_test.planning import verify_execution_plan

    scope = _factor_runtime_scope(payload)
    with scope:
        verify_execution_plan(kind, payload)
        if cancel_event.is_set():
            sink.emit_error(f"{kind} job cancelled before start", cancelled=True)
            return
        sink.emit_start(total=1, groups=1, phase="compute")
        if kind == "factor_evaluation":
            from server.modules.single_factor_test.evaluation import FactorEvaluation

            result = FactorEvaluation.from_run_spec(payload).run()
        else:
            from tools.factors.tester_calc.single_factor_test.factor_type_analysis.server_facade import (
                FactorTypeAnalysisRun,
            )

            result = FactorTypeAnalysisRun.from_run_spec(payload).run()
        if cancel_event.is_set():
            sink.emit_error(f"{kind} job cancelled", cancelled=True)
            return
        sink.emit_progress(1, 1, "compute")
        sink.emit_result(result)


def run_factor_evaluation(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    _run_analysis(payload, sink, cancel_event, kind="factor_evaluation")


def run_factor_type_analysis(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    _run_analysis(payload, sink, cancel_event, kind="factor_type_analysis")


def _typed_ic_execution_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project one frozen Slice-1 core onto the established IC runtime view.

    This is an execution-only projection.  The immutable grouped configuration
    remains authoritative in ``run_spec.typed_ic`` and is never written back to
    the authoring configuration.
    """
    run_spec = payload.get("run_spec") or {}
    typed = run_spec.get("typed_ic")
    if not isinstance(typed, dict):
        return payload
    requests = typed.get("authoring_core_tests") or []
    if not isinstance(requests, list) or len(requests) != 1:
        raise ValueError("Slice 1 typed IC execution requires exactly one core request")
    core = requests[0]
    scope_refs = core.get("product_scope_refs") or []
    factor_refs = core.get("factor_refs") or []
    if len(scope_refs) != 1 or len(factor_refs) != 1:
        raise ValueError("Slice 1 typed IC core requires one scope and one factor")
    scope_ref, factor_ref = str(scope_refs[0]), str(factor_refs[0])
    selections = (run_spec.get("configuration") or {}).get("shared", {}).get(
        "product_selections", {}
    )
    selection = selections.get(scope_ref) if isinstance(selections, dict) else None
    if not isinstance(selection, dict):
        raise ValueError(f"typed IC scope is not frozen: {scope_ref}")
    paths = deepcopy(selection.get("paths") or selection.get("selected_paths") or [])
    if not paths:
        raise ValueError(f"typed IC scope has no frozen paths: {scope_ref}")

    execution = deepcopy(payload)
    execution["product_path_selection_id"] = scope_ref
    execution["product_path_selection"] = {
        **deepcopy(selection),
        "product_path_selection_id": scope_ref,
        "paths": paths,
    }
    execution["paths"] = paths
    frozen_factors = (
        (run_spec.get("configuration") or {}).get("shared", {}).get("factors")
        or execution.get("factors") or []
    )
    matches = []
    for item in frozen_factors:
        try:
            frozen_factor = require_frozen_factor(item)
        except (TypeError, ValueError):
            continue
        if frozen_factor["ref"] == factor_ref:
            matches.append(frozen_factor)
    if len(matches) != 1:
        raise ValueError(f"typed IC factor descriptor is not frozen: {factor_ref}")
    # Preserve the complete records and dependency graph.  Normalizing through
    # require_frozen_factor here would retain identity only and strand nested
    # FactorParam refs in the worker.
    execution["factors"] = deepcopy(frozen_factors)
    execution["factor_ref"] = factor_ref
    execution["ic_lags"] = list(core.get("entry_delay_bars") or [0])
    methods = [str(value) for value in core.get("methods") or []]
    execution["ic_correlation"] = (
        "both" if set(methods) == {"rank", "pearson"}
        else methods[0] if methods else "rank"
    )
    execution["return_price_basis"] = str(
        core.get("return_price_basis") or "next_open_to_open_adjusted"
    )
    group_settings = (typed.get("group_execution_settings") or {}).get(
        str(core.get("request_ref") or ""), {}
    )
    execution["warmup_mode"] = str(group_settings.get("warmup_mode") or "auto")
    execution["warmup_window"] = group_settings.get("warmup_window", "30d")
    resolved_by_factor = (
        (typed.get("resolved_horizons_by_request") or {})
        .get(str(core.get("request_ref") or ""), {})
        .get(factor_ref, [])
    )
    resolved_horizons = list(dict.fromkeys(
        str(item.get("physical_frequency") or "").strip()
        for item in resolved_by_factor
        if isinstance(item, dict) and item.get("physical_frequency")
    ))
    if not resolved_horizons:
        raise ValueError(f"typed IC core has no frozen horizons: {core.get('request_ref')}")
    execution["forward_return_horizons"] = {
        "sampling": "explicit",
        "bases": resolved_horizons,
        "multipliers": [1],
    }
    execution["typed_ic_core_ref"] = str(core.get("request_ref") or "")
    return execution


def run_ic(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    from server.modules.single_factor_test.planning import verify_execution_plan
    from server.modules.single_factor_test.ic import execute_ic_run_spec

    scope = _factor_runtime_scope(payload)
    with scope:
        verify_execution_plan("ic", payload)
        execute_ic_run_spec(
            _typed_ic_execution_payload(payload),
            sink=sink,
            cancel_event=cancel_event,
        )
