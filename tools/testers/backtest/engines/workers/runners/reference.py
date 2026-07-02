"""Framework-free reference implementation of the group-strategy replay.

This is the exact pure-python loop that the backtrader and zipline runners
previously duplicated verbatim (their bodies were byte-identical modulo the
engine name). Extracting it gives two things:

1. one place to fix replay semantics instead of N copies;
2. an in-process execution path for native-vs-framework consistency tests —
   no conda worker environments needed to exercise the worker replay
   semantics themselves.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from .common import (
    apply_deltas,
    executable_deltas,
    execution_delay_bars,
    execution_timing,
    execution_trace_entry,
    market_rule_diagnostics,
    parse_group_strategy_input,
    portfolio_value,
    position_value_snapshot,
    setting_fallback_diagnostics,
    should_report_progress,
    target_quantities,
)


def run_group_strategy(
    payload: Mapping[str, Any], progress=None, *, engine: str = "reference"
) -> dict[str, Any]:
    """ADR-029 event order: the order is SIZED at the SIGNAL bar (target
    quantities, cash rescale, lot floor all use the signal bar's prices and
    equity — the same values native's SIGNAL-phase size_order/cash-constraint
    flows read) and FILLED at the due bar's price (matching_policy=
    next_bar_open_full_fill). Deferring sizing to the fill bar is exactly the
    drift the native-vs-worker consistency test rejects."""
    request, memberships, updates, calculators = parse_group_strategy_input(payload)
    portfolios = {}
    total_replay_steps = len(request.timestamps) * len(request.strategies)
    for strategy_position, (strategy, calculator) in enumerate(
        zip(request.strategies, calculators, strict=True)
    ):
        strategy_cash = float(strategy.get("initial_capital") or request.initial_cash)
        cash = strategy_cash
        positions = {instrument: 0.0 for instrument in request.instruments}
        pending_deltas: list[tuple[int, dict[str, float]]] = []
        equity_curve = {}
        position_curve = {}
        notional_curve = {}
        margin_curve = {}
        execution_trace = {}
        execution_trace_count = 0
        collect_trace = bool(strategy.get("collect_execution_trace"))
        timing = execution_timing(strategy)
        delay_bars = execution_delay_bars(strategy)

        def _size_at_signal(row: int, target) -> dict[str, float]:
            value = portfolio_value(request, row, positions, cash)
            desired = target_quantities(request, row, target, value, strategy)
            return executable_deltas(request, row, strategy, desired, positions, cash)

        for row, timestamp in enumerate(request.timestamps):
            due = [deltas for due_row, deltas in pending_deltas if due_row <= row]
            pending_deltas = [
                (due_row, deltas) for due_row, deltas in pending_deltas if due_row > row
            ]
            for deltas in due:
                before = dict(positions)
                cash_before = cash
                cash, positions = apply_deltas(request, row, strategy, positions, cash, deltas)
                if any(abs(delta) > 1e-12 for delta in deltas.values()):
                    execution_trace_count += 1
                    if collect_trace:
                        execution_trace[timestamp.isoformat()] = execution_trace_entry(
                            request, row, strategy, before, deltas, cash_before
                        )
            target = calculator.update(
                timestamp,
                np.asarray([request.prices[name][row] for name in request.instruments]),
                memberships[row],
                updates[row],
                np.asarray(request.margin_ratios[row]),
            )
            if target is not None:
                deltas = _size_at_signal(row, target)
                if timing == "same_bar":
                    before = dict(positions)
                    cash_before = cash
                    cash, positions = apply_deltas(request, row, strategy, positions, cash, deltas)
                    if any(abs(delta) > 1e-12 for delta in deltas.values()):
                        execution_trace_count += 1
                        if collect_trace:
                            execution_trace[timestamp.isoformat()] = execution_trace_entry(
                                request, row, strategy, before, deltas, cash_before
                            )
                else:
                    pending_deltas.append((row + delay_bars, deltas))
            equity_curve[timestamp.isoformat()] = float(
                portfolio_value(request, row, positions, cash)
            )
            position_curve[timestamp.isoformat()] = dict(positions)
            notional_values, margin_values = position_value_snapshot(
                request, row, strategy, positions
            )
            notional_curve[timestamp.isoformat()] = notional_values
            if margin_values is not None:
                margin_curve[timestamp.isoformat()] = margin_values
            if (
                progress is not None
                and should_report_progress(
                    strategy_position * len(request.timestamps) + row + 1,
                    total_replay_steps,
                )
            ):
                progress(
                    strategy_position * len(request.timestamps) + row + 1,
                    total_replay_steps,
                    timestamp,
                )
        portfolios[calculator.strategy_id] = {
            "initial_value": strategy_cash,
            "final_value": float(portfolio_value(request, len(request.timestamps) - 1, positions, cash)),
            "positions": positions,
            "equity_curve": equity_curve,
            "position_curve": position_curve,
            "notional_curve": notional_curve,
            "margin_curve": margin_curve,
            "execution_trace": execution_trace,
            "execution_trace_count": execution_trace_count,
        }
    return {
        "engine": engine,
        "portfolios": portfolios,
        "target_trace": {item.strategy_id: item.target_trace for item in calculators},
        "execution_trace": {
            strategy_id: portfolio.get("execution_trace", {})
            for strategy_id, portfolio in portfolios.items()
        },
        "strategy_diagnostics": {
            item.strategy_id: {
                **item.diagnostics,
                **market_rule_diagnostics(payload),
                **setting_fallback_diagnostics(strategy),
            }
            for item, strategy in zip(calculators, request.strategies, strict=True)
        },
        "event_count": len(request.timestamps),
        "signal_kind": payload.get("signal_kind"),
    }
