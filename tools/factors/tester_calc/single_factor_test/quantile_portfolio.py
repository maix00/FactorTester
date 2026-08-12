"""Fast, non-event quantile portfolio statistics for IC jobs.

This module deliberately stops at proportional portfolio returns.  It does not
model orders, lots, fills, DMTM, or liquidity; those remain event-backtest
semantics.  The fixed-margin mode is therefore a normalized screening result.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools.data.types.time_index import DataIndex
from tools.factors.tester_calc.single_factor_test.portfolio_metrics import (
    compute_return_metrics,
    portfolio_metric_semantics_catalog,
)


QUANTILE_PORTFOLIO_SCHEMA = "quantile-portfolio-statistics-v1"
DEFAULT_QUANTILE_PORTFOLIO = {
    "enabled": True,
    "group_count": 5,
    "modes": ("no_fee", "fee_margin_target"),
    "target_margin_utilization": 0.30,
}


def _panel(value: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame) or value.empty:
        raise ValueError(f"{name} must be a non-empty DataFrame")
    frame = value.copy(deep=False)
    signal_index = DataIndex(frame.index).signal_index
    frame.index = signal_index
    if frame.index.has_duplicates:
        frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def _aligned_panels(
    factor: pd.DataFrame,
    forward: pd.DataFrame,
    eligibility: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    factor = _panel(factor, "factor_panel")
    forward = _panel(forward, "forward_return_panel")
    def names(frame: pd.DataFrame) -> dict[str, Any]:
        return {str(getattr(column, "name", column)): column for column in frame.columns}

    factor_columns = names(factor)
    forward_columns = names(forward)
    common_names = sorted(set(factor_columns) & set(forward_columns))
    if not common_names:
        raise ValueError("factor and forward-return panels have no aligned observations")
    # Native group selection uses the instrument name as the deterministic tie
    # break.  Canonicalising columns here makes the vectorized path independent
    # of the order in which products arrived from the data provider.
    columns = common_names
    index = factor.index.intersection(forward.index)
    if not len(index):
        raise ValueError("factor and forward-return panels have no aligned observations")
    factor = factor.loc[index, [factor_columns[name] for name in columns]].copy()
    forward = forward.loc[index, [forward_columns[name] for name in columns]].copy()
    factor.columns = columns
    forward.columns = columns
    if eligibility is None:
        eligible = pd.DataFrame(True, index=index, columns=columns)
    else:
        raw_eligibility = _panel(eligibility, "eligibility")
        eligibility_columns = names(raw_eligibility)
        eligible = raw_eligibility.reindex(
            index=index,
            columns=[eligibility_columns.get(name) for name in columns],
        )
        eligible.columns = columns
        eligible = eligible.fillna(False)
    return factor, forward, eligible.astype(bool)


def _labels(values: np.ndarray, eligible: np.ndarray, groups: int) -> np.ndarray:
    valid = eligible & np.isfinite(values)
    safe = np.where(valid, -values, np.inf)
    order = np.argsort(safe, axis=1, kind="stable")
    positions = np.empty_like(order, dtype=float)
    positions[np.arange(len(values))[:, None], order] = np.arange(values.shape[1], dtype=float)
    count = valid.sum(axis=1).astype(float)
    starts = np.rint(np.arange(groups)[None, :] * count[:, None] / groups).astype(int)
    ends = np.rint(np.arange(1, groups + 1)[None, :] * count[:, None] / groups).astype(int)
    labels = np.full(values.shape, -1, dtype=np.int16)
    for group in range(groups):
        selected = valid & (positions >= starts[:, group, None]) & (positions < ends[:, group, None])
        labels[selected] = group
    return labels


def _group_returns(labels: np.ndarray, returns: np.ndarray, groups: int) -> np.ndarray:
    output = np.full((len(labels), groups), np.nan, dtype=float)
    finite = np.isfinite(returns)
    for group in range(groups):
        selected = (labels == group) & finite
        count = selected.sum(axis=1)
        total = np.where(selected, returns, 0.0).sum(axis=1)
        output[:, group] = np.divide(total, count, out=np.full(len(labels), np.nan), where=count > 0)
    return output


def _weights(
    labels: np.ndarray,
    group: int,
    groups: int,
    returns: np.ndarray,
) -> np.ndarray:
    # A missing forward label is not a zero return position.  Exclude it from
    # both the equal-notional denominator and the margin budget, otherwise the
    # last horizon rows are silently diluted compared with the event projector.
    selected = (labels == group) & np.isfinite(returns)
    count = selected.sum(axis=1)
    return np.divide(
        selected.astype(float), count[:, None],
        out=np.zeros(selected.shape, dtype=float), where=count[:, None] > 0,
    )


def _portfolio_return(
    weights: np.ndarray,
    returns: np.ndarray,
    *,
    mode: str,
    margin_rates: np.ndarray,
    open_fees: np.ndarray,
    close_fees: np.ndarray,
    target_margin_utilization: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    weights = np.asarray(weights, dtype=float)
    gross = np.where(np.isfinite(returns), returns, 0.0)
    base = (weights * gross).sum(axis=1)
    valid_position = np.abs(weights).sum(axis=1) > 0
    if mode == "no_fee":
        scale = np.ones(len(weights), dtype=float)
        scaled = weights
        fee = np.zeros(len(weights), dtype=float)
    elif mode == "fee_margin_target":
        margin = (np.abs(weights) * margin_rates).sum(axis=1)
        scale = np.divide(
            target_margin_utilization, margin,
            out=np.zeros(len(weights), dtype=float), where=margin > 0,
        )
        scaled = weights * scale[:, None]
    else:
        raise ValueError(f"unsupported quantile portfolio mode: {mode}")
    last_valid = np.maximum.accumulate(
        np.where(valid_position, np.arange(len(weights)), -1),
    )
    previous_index = np.concatenate((np.array([-1]), last_valid[:-1]))
    previous = np.zeros_like(scaled)
    has_previous = previous_index >= 0
    previous[has_previous] = scaled[previous_index[has_previous]]
    if mode == "fee_margin_target":
        # Open/close is determined by the change in absolute exposure.  A
        # more-negative target opens a short, while a less-negative target
        # closes it; using sign(delta) alone reverses those two cases.
        open_amount = (
            np.maximum(np.maximum(scaled, 0.0) - np.maximum(previous, 0.0), 0.0)
            + np.maximum(np.maximum(-scaled, 0.0) - np.maximum(-previous, 0.0), 0.0)
        )
        close_amount = (
            np.maximum(np.maximum(previous, 0.0) - np.maximum(scaled, 0.0), 0.0)
            + np.maximum(np.maximum(-previous, 0.0) - np.maximum(-scaled, 0.0), 0.0)
        )
        fee = -(open_amount * open_fees + close_amount * close_fees).sum(axis=1)
    turnover = np.abs(
        scaled - previous
    ).sum(axis=1)
    # An empty quantile is an unobservable portfolio period, not a zero-return
    # observation.  Exclude it from metrics and from the turnover average so
    # missing eligibility cannot manufacture performance or trading costs.
    net = np.where(valid_position, base * scale + fee, np.nan)
    gross_net = np.where(valid_position, base * scale, np.nan)
    turnover = np.where(valid_position, turnover, np.nan)
    return net, gross_net, scale, turnover


def _monotonicity(group_returns: np.ndarray) -> dict[str, Any]:
    valid = np.isfinite(group_returns).all(axis=1)
    comparable = group_returns[valid]
    if not len(comparable):
        return {"comparable_period_count": 0, "monotonic_period_ratio": None}
    diffs = np.diff(comparable, axis=1)
    descending = np.all(diffs <= 0, axis=1)
    ascending = np.all(diffs >= 0, axis=1)
    monotonic = descending | ascending
    ranks = pd.DataFrame(comparable).rank(axis=1, method="average").to_numpy(dtype=float)
    axis = np.arange(1, comparable.shape[1] + 1, dtype=float)
    x = axis - axis.mean()
    y = ranks - ranks.mean(axis=1, keepdims=True)
    denominator = np.sqrt((y * y).sum(axis=1) * (x * x).sum())
    corr = np.divide(
        (y * x).sum(axis=1), denominator,
        out=np.full(len(comparable), np.nan), where=denominator > 0,
    )
    finite_corr = corr[np.isfinite(corr)]
    adjacent = comparable[:, :-1] - comparable[:, 1:]
    return {
        "comparable_period_count": int(len(comparable)),
        "full_group_period_ratio": float(valid.mean()),
        "monotonic_period_ratio": float(monotonic.mean()),
        "descending_period_ratio": float(descending.mean()),
        "mean_rank_correlation": float(np.mean(finite_corr)) if len(finite_corr) else None,
        "top_bottom": {
            "mean_spread": float(np.mean(comparable[:, 0] - comparable[:, -1])),
            "positive_ratio": float(np.mean(comparable[:, 0] > comparable[:, -1])),
        },
        "adjacent_spreads": [
            {"from_group": i, "to_group": i + 1,
             "mean_spread": float(np.mean(adjacent[:, i])),
             "positive_ratio": float(np.mean(adjacent[:, i] > 0))}
            for i in range(adjacent.shape[1])
        ],
    }


def _metric_row(returns: np.ndarray, index: pd.Index, turnover: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(returns)
    metric_index = index[finite] if len(index) == len(finite) else index
    finite_turnover = turnover[np.isfinite(turnover)]
    metrics = compute_return_metrics(
        returns,
        index_like=metric_index,
        avg_turnover=(float(np.mean(finite_turnover)) if len(finite_turnover) else None),
    )
    metrics.update({
        "n_periods": int(np.isfinite(returns).sum()),
        "cumulative_return": float(np.prod(1.0 + returns[np.isfinite(returns)]) - 1.0) if np.isfinite(returns).any() else None,
        "mean_period_return": float(np.nanmean(returns)) if np.isfinite(returns).any() else None,
    })
    return metrics


def compute_quantile_portfolio_statistics(
    factor_panel: pd.DataFrame,
    forward_return_panel: pd.DataFrame,
    *,
    group_count: int = 5,
    eligibility: pd.DataFrame | None = None,
    margin_rates: Sequence[float] | np.ndarray | None = None,
    open_fee_rates: Sequence[float] | np.ndarray | None = None,
    close_fee_rates: Sequence[float] | np.ndarray | None = None,
    modes: Sequence[str] = ("no_fee", "fee_margin_target"),
    target_margin_utilization: float = 0.30,
    initial_capital: float = 1.0,
    include_return_series: bool = False,
) -> dict[str, Any]:
    """Compute grouped returns without creating orders or integer positions."""
    if int(group_count) < 2:
        raise ValueError("group_count must be at least 2")
    if not 0 < float(target_margin_utilization) < 1:
        raise ValueError("target_margin_utilization must be between 0 and 1")
    if float(initial_capital) <= 0:
        raise ValueError("initial_capital must be positive")
    factor, forward, eligible = _aligned_panels(factor_panel, forward_return_panel, eligibility)
    valid_rows = np.isfinite(forward.to_numpy(dtype=float)).any(axis=1)
    factor = factor.loc[valid_rows]
    forward = forward.loc[valid_rows]
    eligible = eligible.loc[valid_rows]
    if factor.empty:
        raise ValueError("forward-return panel has no finite observations")
    names = list(factor.columns)
    shape = len(names)
    margin = np.asarray(margin_rates if margin_rates is not None else np.ones(shape), dtype=float)
    open_fee = np.asarray(open_fee_rates if open_fee_rates is not None else np.zeros(shape), dtype=float)
    close_fee = np.asarray(close_fee_rates if close_fee_rates is not None else open_fee, dtype=float)
    for value, label in ((margin, "margin_rates"), (open_fee, "open_fee_rates"), (close_fee, "close_fee_rates")):
        if value.shape != (shape,) or np.any(~np.isfinite(value)) or np.any(value < 0):
            raise ValueError(f"{label} must contain one finite non-negative value per product")
    labels = _labels(factor.to_numpy(dtype=float), eligible.to_numpy(dtype=bool), int(group_count))
    returns = _group_returns(labels, forward.to_numpy(dtype=float), int(group_count))
    result: dict[str, Any] = {
        "schema_version": QUANTILE_PORTFOLIO_SCHEMA,
        "artifact_kind": "quantile_portfolio_statistics",
        "initial_capital": float(initial_capital),
        "capital_normalization": "unit_equity_decimal",
        "normalization_exact_when": ["proportional_fee_rates", "no_lot_rounding", "no_fixed_currency_fees", "no_liquidity_cap"],
        "group_count": int(group_count),
        "product_count": int(shape),
        "period_count": int(len(factor)),
        "target_margin_utilization": float(target_margin_utilization),
        "rate_semantics": "per_product_static_ratio_inputs",
        "metric_semantics": portfolio_metric_semantics_catalog(),
        "turnover_semantics": {
            "metric": "Avg Turnover",
            "unit": "decimal_ratio",
            "basis": "mean absolute change in target notional weights per period",
            "status": "proxy; excludes fills, lot rounding, liquidity and fixed fees",
        },
        "modes": {},
    }
    for mode in modes:
        mode = str(mode)
        mode_groups = []
        mode_returns = np.full_like(returns, np.nan)
        mode_turnover = []
        for group in range(int(group_count)):
            weights = _weights(labels, group, int(group_count), forward.to_numpy(dtype=float))
            net, _gross, _scale, turnover = _portfolio_return(
                weights, forward.to_numpy(dtype=float), mode=mode,
                margin_rates=margin, open_fees=open_fee, close_fees=close_fee,
                target_margin_utilization=float(target_margin_utilization),
            )
            mode_returns[:, group] = net
            mode_turnover.append(turnover)
            group_item = {"group_index": group, "metrics": _metric_row(net, factor.index, turnover)}
            if include_return_series:
                group_item["period_returns"] = [
                    float(value) if np.isfinite(value) else None for value in net
                ]
            mode_groups.append(group_item)
        turnover_matrix = np.column_stack(mode_turnover)
        top_weights = 0.5 * _weights(
            labels, 0, int(group_count), forward.to_numpy(dtype=float),
        )
        bottom_weights = -0.5 * _weights(
            labels, int(group_count) - 1, int(group_count), forward.to_numpy(dtype=float),
        )
        ls, _gross, _scale, ls_turnover = _portfolio_return(
            top_weights + bottom_weights, forward.to_numpy(dtype=float), mode=mode,
            margin_rates=margin, open_fees=open_fee, close_fees=close_fee,
            target_margin_utilization=float(target_margin_utilization),
        )
        long_short = {"metrics": _metric_row(ls, factor.index, ls_turnover)}
        if include_return_series:
            long_short["period_returns"] = [
                float(value) if np.isfinite(value) else None for value in ls
            ]
        result["modes"][mode] = {
            "groups": mode_groups,
            "long_short": long_short,
            "monotonicity": _monotonicity(mode_returns),
            "turnover_proxy": (
                float(np.nanmean(turnover_matrix))
                if np.isfinite(turnover_matrix).any() else None
            ),
            "long_short_turnover_proxy": (
                float(np.nanmean(ls_turnover))
                if np.isfinite(ls_turnover).any() else None
            ),
        }
    return result


def compare_quantile_portfolio_statistics(
    quick: Mapping[str, Any],
    formal: Mapping[str, Any],
    *,
    mode: str = "no_fee",
    metrics: Sequence[str] = ("Total Return", "Max Drawdown", "Sharpe Ratio"),
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Compare normalized quick metrics with one formal group result.

    The comparison is metric-level by design.  Formal event results may have
    different timestamp density because of fills and settlements; a matching
    return series is a separate, stricter audit rather than an implicit claim.
    """
    quick_mode = (quick.get("modes") or {}).get(mode) or {}
    formal = formal_group_statistics(formal)
    quick_groups = {
        int(item.get("group_index")): item.get("metrics") or {}
        for item in quick_mode.get("groups") or ()
        if isinstance(item, Mapping) and item.get("group_index") is not None
    }
    formal_metrics_by_key = formal.get("metrics") or {}
    formal_groups = {}
    for item in formal.get("groups") or ():
        if not isinstance(item, Mapping) or item.get("group_index") is None:
            continue
        group_metrics = item.get("metrics")
        if not isinstance(group_metrics, Mapping):
            key = item.get("metrics_key") or item.get("name") or item.get("key")
            group_metrics = formal_metrics_by_key.get(key) or {}
        formal_groups[int(item.get("group_index"))] = dict(group_metrics)
    rows: list[dict[str, Any]] = []
    for group_index in sorted(set(quick_groups) | set(formal_groups)):
        q_metrics = quick_groups.get(group_index, {})
        f_metrics = formal_groups.get(group_index, {})
        metric_rows = {}
        for name in metrics:
            q_value = q_metrics.get(name)
            f_value = f_metrics.get(name)
            try:
                error = abs(float(q_value) - float(f_value))
            except (TypeError, ValueError):
                error = None
            metric_rows[name] = {
                "quick": q_value,
                "formal": f_value,
                "absolute_error": error,
                "within_tolerance": error is not None and error <= tolerance,
            }
        rows.append({"group_index": group_index, "metrics": metric_rows})
    errors = [
        metric["absolute_error"]
        for row in rows
        for metric in row["metrics"].values()
        if metric["absolute_error"] is not None
    ]
    return {
        "schema_version": 1,
        "mode": mode,
        "tolerance": float(tolerance),
        "groups": rows,
        "max_absolute_error": max(errors) if errors else None,
        "status": "within_tolerance" if errors and max(errors) <= tolerance else "different",
    }


def formal_group_statistics(formal: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an event projection for metric-level quick-path comparison.

    ``serialize_event_execution`` stores the formal group metrics under
    ``serialized_execution`` when it is embedded in a Job result.  The
    vectorized IC path deliberately does not depend on that module, so this
    small adapter lives here and accepts either the embedded result or the
    already-unwrapped projection.  It copies only scalar metric maps; event
    curves, orders, fills, and audit traces are never duplicated.
    """
    if not isinstance(formal, Mapping):
        return {"groups": []}
    candidate = formal.get("serialized_execution")
    if isinstance(candidate, Mapping):
        formal = candidate
    groups = []
    metrics_by_key = formal.get("metrics") or {}
    for item in formal.get("groups") or ():
        if not isinstance(item, Mapping) or item.get("group_index") is None:
            continue
        metrics = item.get("metrics")
        if not isinstance(metrics, Mapping):
            metrics = metrics_by_key.get(
                item.get("metrics_key") or item.get("name") or item.get("key"),
            ) or {}
        groups.append({
            "group_index": int(item["group_index"]),
            "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        })
    return {"groups": groups, "metrics": {}}


__all__ = [
    "QUANTILE_PORTFOLIO_SCHEMA", "DEFAULT_QUANTILE_PORTFOLIO",
    "compute_quantile_portfolio_statistics", "compare_quantile_portfolio_statistics",
    "formal_group_statistics",
]
