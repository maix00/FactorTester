"""Execute one frozen grouped-research RunSpec."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.factors.tester_calc.single_factor_test.group.metadata import (
    GROUP_TEST_METRICS_META,
)

from .preparation import prepare_group_run_spec
from .projection import serialize_event_execution
from .settings import silent_default_settings_for_run


def execute_group_run_spec(
    data: dict[str, Any],
    *,
    sink: Any,
    cancel_event: Any,
) -> None:
    """Execute a frozen group RunSpec without page-runtime state."""
    from server.services.external_factor_artifacts import result_metadata
    from tools.factors.FactorTester import FactorTester
    from tools.testers.backtest.engines.cancellation import BacktestCancelled
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.strategy_config_builder import (
        apply_strategy_configs,
    )

    prepared = prepare_group_run_spec(data)
    payload = prepared["payload"]
    run_id = prepared["run_id"]
    flat_groups = prepared["flat_groups"]
    flat_ls_configs = prepared["flat_ls_configs"]
    resolved_backtest_settings = prepared["resolved_backtest_settings"]
    resolved_settings_by_alias = prepared["resolved_settings_by_alias"]
    group_owner = prepared["group_owner"]
    all_products = prepared["all_products"]
    market_rule_fallback = prepared["market_rule_fallback"]
    evaluation_split = prepared["evaluation_split"]
    run_registry = prepared["run_registry"]
    factor_mode = prepared["factor_mode"]
    start_dt = prepared["start_dt"]
    end_dt = prepared["end_dt"]
    step_mode = bool(payload.get("step_mode"))

    account = BacktestRunState()
    strategy_book_payload = payload.get("strategy_book")
    strategy_book = None
    if isinstance(strategy_book_payload, dict) and strategy_book_payload:
        from tools.testers.backtest.modules.strategy_book import StrategyBook

        strategy_book = StrategyBook.from_dict(strategy_book_payload)
    ledger_configs = payload.get("ledger_configs")
    if ledger_configs is not None and not isinstance(ledger_configs, dict):
        raise ValueError("ledger_configs 必须是对象")
    apply_strategy_configs(
        account,
        resolved_settings_by_alias,
        strategy_book=strategy_book,
        ledger_configs=ledger_configs,
    )
    account.runtime_info_sink = sink
    account.market_data_request = {
        "products": all_products,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "policy": market_rule_fallback,
    }

    def on_progress(completed: int, total: int, label: str) -> None:
        if cancel_event.is_set():
            raise BacktestCancelled("group job cancelled")
        sink.emit_progress(
            completed,
            total,
            "event_replay",
            message=label,
        )

    tester = FactorTester(products=[], alias=f"group_run:{run_id[:8]}")
    step_callback = None
    if step_mode:
        after_index = max(0, int(payload.get("step_after_index") or 0))
        raw_until = str(payload.get("step_until") or "").strip()
        until = pd.Timestamp(raw_until).tz_localize(None) if raw_until else None
        cursor = {"flow_index": 0, "until": until, "run_to_end": False}

        def should_capture(timestamp: Any) -> bool:
            cursor["flow_index"] += 1
            if cursor["run_to_end"]:
                return False
            if cursor["flow_index"] <= after_index:
                return False
            if cursor["until"] is None:
                return True
            if timestamp is None:
                return False
            return pd.Timestamp(timestamp).tz_localize(None) >= cursor["until"]

        def checkpoint(info: dict[str, Any]) -> None:
            checkpoint_payload = {
                **info,
                "flow_index": cursor["flow_index"],
            }
            sink.emit_step(checkpoint_payload)
            command = sink.emit_pause(checkpoint_payload) or {}
            action = str(command.get("action") or "continue")
            if action == "cancel":
                raise BacktestCancelled("group step job cancelled")
            if action == "end":
                cursor["run_to_end"] = True
                return
            raw_next_until = str(command.get("until") or "").strip()
            cursor["until"] = (
                pd.Timestamp(raw_next_until).tz_localize(None)
                if raw_next_until
                else None
            )

        setattr(checkpoint, "should_capture", should_capture)
        step_callback = checkpoint

    try:
        execution = tester.dispatch(
            "backtest",
            run_state=account,
            group_owner=group_owner,
            settings_by_strategy=resolved_settings_by_alias,
            run_id=run_id,
            progress=on_progress,
            activity_sink=sink,
            step_mode=step_mode,
            step_callback=step_callback,
        )
    except BacktestCancelled as exc:
        sink.emit_error(
            str(exc),
            cancelled=True,
            cancel_reason="explicit_cancel",
        )
        return

    serialized_execution = serialize_event_execution(
        execution,
        settings_by_group=execution["settings_by_strategy"],
        evaluation_split=evaluation_split,
        registry=run_registry,
    )
    from server.modules.single_factor_test.backtest_research_artifacts import (
        project_net_returns,
    )

    net_returns = project_net_returns(
        engine_result=execution["engine_result"],
        group_owner=execution["group_owner"],
    )
    if net_returns is not None:
        sink.emit_artifact("net_returns", net_returns)
    event_execution = {
        "run_id": execution["payload"]["run_id"],
        "engine_result": execution["engine_result"],
        "group_owner": execution["group_owner"],
        "serialized_execution": serialized_execution,
        "detail_context": {
            "payload": {
                "instruments": execution["payload"].get("instruments") or [],
                "market_rules": execution["payload"].get("market_rules") or {},
            },
            "settings_by_strategy": execution["settings_by_strategy"],
        },
    }
    sink.emit_artifact("group_execution", event_execution)
    first_owner = group_owner[0]
    sink.emit_result({
        "success": True,
        "run_id": run_id,
        **serialized_execution,
        "metrics_meta": GROUP_TEST_METRICS_META,
        "n_groups": len(serialized_execution["groups"]),
        "runtime_info_rows": list(
            getattr(account, "runtime_info_rows", ())
        ),
        "product_path_selection_id": str(
            first_owner.get("product_path_selection_id") or ""
        ),
        "factor_alias": str(first_owner.get("factor_alias") or ""),
        "product_path_selection_count": len(all_products),
        "simulation_count": 1,
        "cross_entry_ls_count": len(flat_ls_configs),
        "errors": None,
        "external_factor_artifacts": result_metadata(
            payload.get("external_factor_artifacts")
        ),
        "backtest_settings": {
            "engine": "native",
            "factor_mode": factor_mode,
            "market_rule_fallback": market_rule_fallback,
            "groups": resolved_backtest_settings,
        },
        "silent_default_settings": silent_default_settings_for_run(
            payload,
            flat_groups,
            flat_ls_configs,
            resolved_backtest_settings,
        ),
    })
