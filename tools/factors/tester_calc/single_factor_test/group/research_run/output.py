"""Project and emit retained grouped-backtest outputs."""

from __future__ import annotations

from typing import Any

from tools.factors.tester_calc.single_factor_test.group.metadata import (
    GROUP_TEST_METRICS_META,
)
from tools.testers.backtest.modules.order_lifecycle.artifact import (
    emit_order_audit_artifact,
)

from .projection import serialize_event_execution
from .settings import silent_default_settings_for_run
from ..strategy_analysis import build_strategy_analysis_source


def emit_group_run_outputs(
    *, sink: Any, execution: dict[str, Any], prepared: dict[str, Any], account: Any,
) -> None:
    from server.modules.single_factor_test.backtest_research_artifacts import (
        project_net_returns,
    )
    from server.services.external_factor_artifacts import result_metadata
    from tools.testers.backtest.engines.native.effective_settings import (
        build_effective_runtime_settings,
    )

    payload = prepared["payload"]
    run_id = prepared["run_id"]
    group_owner = prepared["group_owner"]
    serialized = serialize_event_execution(
        execution,
        settings_by_group=execution["settings_by_strategy"],
        evaluation_split=prepared["evaluation_split"],
        registry=prepared["run_registry"],
        include_execution_trace_checksums=(
            str(
                payload.get("result_retention_mode")
                or payload.get("retention_mode")
                or "summary"
            ) == "full"
            or "group_execution" in {
                str(item).strip()
                for item in (payload.get("output_requests") or ())
                if str(item).strip()
            }
        ),
    )
    net_returns = project_net_returns(
        engine_result=execution["engine_result"],
        group_owner=group_owner,
    )
    if net_returns is not None:
        sink.emit_artifact("net_returns", net_returns)
    effective_runtime_settings = build_effective_runtime_settings(
        account,
        settings_by_strategy=execution["settings_by_strategy"],
        products=prepared["all_products"],
    )
    group_execution = {
        "run_id": execution["payload"]["run_id"],
        "engine_result": execution["engine_result"],
        "group_owner": group_owner,
        "serialized_execution": serialized,
        "detail_context": {
            "payload": {
                "instruments": execution["payload"].get("instruments") or [],
                "market_rules": execution["payload"].get("market_rules") or {},
            },
            "settings_by_strategy": execution["settings_by_strategy"],
            "effective_runtime_settings": effective_runtime_settings,
        },
    }
    sink.emit_core_artifact(
        "strategy_analysis_source",
        build_strategy_analysis_source(group_execution, serialized),
    )
    sink.emit_artifact("group_execution", group_execution)
    emit_order_audit_artifact(sink, account, run_id)
    first_owner = group_owner[0]
    result = {
        "success": True,
        "run_id": run_id,
        **serialized,
        "metrics_meta": GROUP_TEST_METRICS_META,
        "n_groups": len(serialized["groups"]),
        "runtime_info_rows": list(getattr(account, "runtime_info_rows", ())),
        "product_path_selection_id": str(
            first_owner.get("product_path_selection_id") or ""
        ),
        "factor_alias": str(first_owner.get("factor_alias") or ""),
        "product_path_selection_count": len(prepared["all_products"]),
        "simulation_count": 1,
        "cross_entry_ls_count": len(prepared["flat_ls_configs"]),
        "errors": None,
        "external_factor_artifacts": result_metadata(
            payload.get("external_factor_artifacts")
        ),
        "backtest_settings": {
            "engine": "native",
            "factor_mode": prepared["factor_mode"],
            "market_rule_fallback": prepared["market_rule_fallback"],
            "groups": prepared["resolved_backtest_settings"],
        },
        "effective_runtime_settings": effective_runtime_settings,
        "silent_default_settings": silent_default_settings_for_run(
            payload,
            prepared["flat_groups"],
            prepared["flat_ls_configs"],
            prepared["resolved_backtest_settings"],
        ),
    }
    sink.emit_result(result, source=group_execution)
