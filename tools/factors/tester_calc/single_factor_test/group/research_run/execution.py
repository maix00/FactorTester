"""Execute one frozen grouped-research RunSpec."""

from __future__ import annotations

from typing import Any

from .output import emit_group_run_outputs
from .preparation import prepare_group_run_spec
from .step_control import build_step_callback
from .strategy_loader import strategy_objects_from_payload
from .strategy_plan_runtime import (
    activate_strategy_plan,
    strategy_aliases_for_plan,
    strategy_plan_from_payload,
    validate_strategy_plan_capabilities,
)


def execute_group_run_spec(
    data: dict[str, Any], *, sink: Any, cancel_event: Any,
) -> None:
    """Execute a frozen group RunSpec without page-runtime state."""
    from tools.factors.FactorTester import FactorTester
    from tools.testers.backtest.engines.cancellation import BacktestCancelled
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.performance_profile import (
        build_backtest_profiler,
    )
    from tools.testers.backtest.modules.margin_budget_impl.observability import (
        build_margin_execution_observer,
    )
    from tools.testers.backtest.engines.native.strategy_config_builder import (
        apply_strategy_configs,
    )

    prepared = prepare_group_run_spec(data)
    payload = prepared["payload"]
    account = BacktestRunState(
        result_retention_mode=_result_retention_mode(payload),
    )
    account.backtest_profiler = build_backtest_profiler(
        payload.get("performance_profile")
    )
    account.margin_execution_observer = build_margin_execution_observer(
        payload.get("margin_execution_profile")
    )
    requested_outputs = {
        str(item).strip()
        for item in (payload.get("output_requests") or ())
        if str(item).strip()
    }
    # Summary jobs that do not retain group_execution never expose the
    # execution-trace checksum.  Avoid canonical JSON hashing in that path;
    # full runs and explicit group_execution requests retain the old checksum
    # contract byte-for-byte.
    retention_mode = str(
        payload.get("result_retention_mode")
        or payload.get("retention_mode")
        or "summary"
    )
    needs_execution_checksum = (
        retention_mode == "full"
        or "group_execution" in requested_outputs
    )
    retain_execution_records = (
        retention_mode == "full"
        or "group_execution" in requested_outputs
        or bool(payload.get("step_mode"))
    )
    account.order_flow_store.enable_streaming(
        compute_checksum=needs_execution_checksum,
        retain_records=retain_execution_records,
    )
    from server.modules.shared.run_spec_resolution.strategies import (
        strategy_book_from_run_spec,
    )

    strategy_book = strategy_book_from_run_spec(payload.get("strategy_book"))
    strategy_plan = strategy_plan_from_payload(payload)
    available_aliases = list(prepared["resolved_settings_by_alias"])
    aliases = strategy_aliases_for_plan(strategy_plan, available_aliases)
    strategy_objects = strategy_objects_from_payload(
        payload, aliases_by_index=aliases,
    )
    resolved_settings = activate_strategy_plan(
        prepared["resolved_settings_by_alias"], strategy_plan, aliases,
    )
    validate_strategy_plan_capabilities(payload, strategy_plan, strategy_objects)
    ledger_configs = payload.get("ledger_configs")
    if ledger_configs is not None and not isinstance(ledger_configs, dict):
        raise ValueError("ledger_configs 必须是对象")
    apply_strategy_configs(
        account,
        resolved_settings,
        strategy_book=strategy_book,
        ledger_configs=ledger_configs,
        strategies_by_alias=strategy_objects,
    )
    account.runtime_info_sink = sink
    account.market_data_request = {
        "products": prepared["all_products"],
        "start_dt": prepared["start_dt"],
        "end_dt": prepared["end_dt"],
        "policy": prepared["market_rule_fallback"],
    }

    def on_progress(completed: int, total: int, label: str) -> None:
        if cancel_event.is_set():
            raise BacktestCancelled("group job cancelled")
        sink.emit_progress(completed, total, "event_replay", message=label)

    try:
        try:
            execution = FactorTester(
                products=[], alias=f"group_run:{prepared['run_id'][:8]}",
            ).dispatch(
                "backtest",
                run_state=account,
                group_owner=prepared["group_owner"],
                settings_by_strategy=resolved_settings,
                run_id=prepared["run_id"],
                progress=on_progress,
                activity_sink=sink,
                step_mode=bool(payload.get("step_mode")),
                step_callback=build_step_callback(payload, sink),
            )
        except BacktestCancelled as exc:
            sink.emit_error(
                str(exc), cancelled=True, cancel_reason="explicit_cancel",
            )
            return
        emit_group_run_outputs(
            sink=sink, execution=execution, prepared=prepared, account=account,
        )
    finally:
        account.order_flow_store.cleanup_streaming()


def _result_retention_mode(payload: dict[str, Any]) -> str:
    """Read the retention decision frozen by the submitting runtime."""
    value = str(
        payload.get("result_retention_mode")
        or payload.get("retention_mode")
        or "summary"
    )
    return value if value in {"summary", "full"} else "summary"
