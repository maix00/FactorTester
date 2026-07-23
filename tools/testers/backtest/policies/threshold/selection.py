"""Causal threshold entry/exit state transitions."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tools.testers.backtest.modules.threshold_signal import ThresholdSignalModule

from .state import last_threshold_selection, last_threshold_weights, signed_weights


def compute_threshold_target_weights(
    state: Any,
    ctx: Any,
    strategy: Any,
    signal_value: dict,
    *,
    factor_values_by_role: dict[str, dict] | None = None,
    previous_selection: dict[str, frozenset] | None = None,
    previous_weights: dict[Any, float] | None = None,
) -> tuple[dict[Any, float], dict[str, frozenset], str]:
    previous_selection = previous_selection or last_threshold_selection(state, strategy)
    if previous_weights is None:
        previous_weights = last_threshold_weights(state, strategy)
    config = state.config_for(strategy)
    mode = str(config.get(ThresholdSignalModule.threshold_mode, "absolute") or "absolute")
    side_mode = str(config.get(ThresholdSignalModule.side_mode, "long_only") or "long_only")
    role_values = factor_values_by_role or {}
    entry_values = role_values.get("entry", signal_value)
    exit_values = role_values.get("exit", signal_value)
    if not entry_values and not exit_values:
        selection = {"long": frozenset(), "short": frozenset()}
        return {}, selection, transition_reason(previous_selection, selection)

    long_members = _side_members(config, entry_values, exit_values, mode, True, previous_selection)
    short_members = _side_members(config, entry_values, exit_values, mode, False, previous_selection)
    if side_mode == "long_only":
        short_members = frozenset()
    elif side_mode == "short_only":
        long_members = frozenset()
    selection = {"long": long_members, "short": short_members}
    if selection == previous_selection and previous_weights is not None:
        return dict(previous_weights), selection, "threshold_hold"
    weights = signed_weights(state, ctx, strategy, long_members, short_members, side_mode)
    return weights, selection, transition_reason(previous_selection, selection)


def _side_members(config, entry_values, exit_values, mode, positive_side, previous_selection):
    side = "long" if positive_side else "short"
    return select_threshold_side(
        entry_values,
        exit_values,
        mode=mode,
        positive_side=positive_side,
        entry=float(config.get(ThresholdSignalModule.entry_threshold, 0.0) or 0.0),
        exit=float(config.get(ThresholdSignalModule.exit_threshold, 0.0) or 0.0),
        quantile_entry=float(config.get(ThresholdSignalModule.quantile_entry, 0.8) or 0.8),
        quantile_exit=float(config.get(ThresholdSignalModule.quantile_exit, 0.6) or 0.6),
        previous=previous_selection.get(side, frozenset()),
    )


def transition_reason(previous: dict[str, frozenset], current: dict[str, frozenset]) -> str:
    previous_members = set(previous.get("long", ())) | set(previous.get("short", ()))
    current_members = set(current.get("long", ())) | set(current.get("short", ()))
    if not previous_members and current_members:
        return "threshold_entry"
    if previous_members and not current_members:
        return "threshold_exit"
    if previous != current:
        return "threshold_transition"
    return "threshold_flat"


def select_threshold_side(
    entry_values: dict,
    exit_values: dict,
    *,
    mode: str,
    positive_side: bool,
    entry: float,
    exit: float,
    quantile_entry: float,
    quantile_exit: float,
    previous: frozenset,
) -> frozenset:
    if mode == "cross_section_quantile":
        entry_cutoff = quantile_cutoff(entry_values, quantile_entry, positive_side) if entry_values else None
        exit_cutoff = quantile_cutoff(exit_values, quantile_exit, positive_side) if exit_values else None
    else:
        entry_cutoff = entry if positive_side else -entry
        exit_cutoff = exit if positive_side else -exit
    return frozenset(
        product for product in set(entry_values) | set(previous)
        if (
            entry_cutoff is not None
            and product in entry_values
            and passes_threshold(entry_values[product], entry_cutoff, positive_side)
        ) or (
            exit_cutoff is not None
            and product in previous
            and product in exit_values
            and passes_threshold(exit_values[product], exit_cutoff, positive_side)
        )
    )


def quantile_cutoff(values: dict, quantile: float, positive_side: bool) -> float:
    q = min(max(float(quantile), 0.0), 1.0)
    return float(pd.Series(list(values.values()), dtype="float64").quantile(q if positive_side else 1.0 - q))


def passes_threshold(value: float, threshold: float, positive_side: bool) -> bool:
    return value >= threshold if positive_side else value <= threshold
