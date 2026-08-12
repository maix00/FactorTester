"""Importable process runners for immutable research RunSpecs."""

from __future__ import annotations

from typing import Any


def _factor_runtime_scope(payload: dict[str, Any]):
    from server.modules.shared.factor_param_resolver import (
        register_factor_param_resolver_for_user,
    )
    from server.services.factor_registry import transient_factor_source_scope

    register_factor_param_resolver_for_user(str(payload.get("_owner") or ""))
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


def run_ic(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    from server.modules.single_factor_test.planning import verify_execution_plan
    from server.modules.single_factor_test.ic import execute_ic_run_spec

    scope = _factor_runtime_scope(payload)
    with scope:
        verify_execution_plan("ic", payload)
        execute_ic_run_spec(payload, sink=sink, cancel_event=cancel_event)
