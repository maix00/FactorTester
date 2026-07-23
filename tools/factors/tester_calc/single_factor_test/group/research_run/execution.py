"""Execute one frozen grouped-research RunSpec."""

from __future__ import annotations

from typing import Any

from .output import emit_group_run_outputs
from .preparation import prepare_group_run_spec
from .step_control import build_step_callback


def execute_group_run_spec(
    data: dict[str, Any], *, sink: Any, cancel_event: Any,
) -> None:
    """Execute a frozen group RunSpec without page-runtime state."""
    from tools.factors.FactorTester import FactorTester
    from tools.testers.backtest.engines.cancellation import BacktestCancelled
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.strategy_config_builder import (
        apply_strategy_configs,
    )

    prepared = prepare_group_run_spec(data)
    payload = prepared["payload"]
    account = BacktestRunState()
    strategy_book = strategy_book_from_payload(payload.get("strategy_book"))
    ledger_configs = payload.get("ledger_configs")
    if ledger_configs is not None and not isinstance(ledger_configs, dict):
        raise ValueError("ledger_configs 必须是对象")
    apply_strategy_configs(
        account,
        prepared["resolved_settings_by_alias"],
        strategy_book=strategy_book,
        ledger_configs=ledger_configs,
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
        execution = FactorTester(
            products=[], alias=f"group_run:{prepared['run_id'][:8]}",
        ).dispatch(
            "backtest",
            run_state=account,
            group_owner=prepared["group_owner"],
            settings_by_strategy=prepared["resolved_settings_by_alias"],
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


def strategy_book_from_payload(value):
    if not isinstance(value, dict) or not value:
        return None
    from tools.testers.backtest.modules.strategy_book import StrategyBook

    return StrategyBook.from_dict(value)
