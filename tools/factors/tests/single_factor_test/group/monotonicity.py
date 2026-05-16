"""Ranking-ability analytics for grouped backtests."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from tools.factors.FactorTester import _signal_time


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def build_group_ranking_detail(group_returns_np: np.ndarray, index_list: list | None = None) -> dict[str, Any]:
    """Summarize whether group returns preserve the factor ranking."""
    returns = np.asarray(group_returns_np, dtype=float)
    if returns.ndim != 2 or returns.shape[1] < 2:
        return {}

    valid = np.isfinite(returns)
    non_empty_counts = valid.sum(axis=1)
    full_rows = valid.all(axis=1)
    comparable = returns[full_rows]

    if comparable.size:
        diffs = np.diff(comparable, axis=1)
        descending_rows = np.all(diffs <= 0, axis=1)
        ascending_rows = np.all(diffs >= 0, axis=1)
        monotonic_rows = descending_rows | ascending_rows
        group_ranks = np.arange(returns.shape[1], dtype=float)
        rank_corrs = []
        for row in comparable:
            corr = pd.Series(group_ranks).corr(pd.Series(row), method='spearman')
            if pd.notna(corr):
                rank_corrs.append(float(corr))
        top_bottom = comparable[:, 0] - comparable[:, -1]
        adjacent = comparable[:, :-1] - comparable[:, 1:]
    else:
        monotonic_rows = np.array([], dtype=bool)
        rank_corrs = []
        top_bottom = np.array([], dtype=float)
        adjacent = np.empty((0, returns.shape[1] - 1), dtype=float)

    spread_series = []
    monotonic_series = []
    if index_list is not None and len(index_list) == len(returns):
        running_nav = 1.0
        for row_idx, idx_entry in enumerate(index_list):
            row = returns[row_idx]
            if not np.isfinite(row).all():
                continue
            row_diffs = np.diff(row)
            is_descending = bool(np.all(row_diffs <= 0))
            is_ascending = bool(np.all(row_diffs >= 0))
            spread = float(row[0] - row[-1])
            running_nav *= 1.0 + spread
            spread_series.append({
                'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
                'spread': spread,
                'cumulative_return': running_nav,
            })
            monotonic_series.append({
                'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
                'is_monotonic': is_descending or is_ascending,
                'is_descending': is_descending,
            })

    adjacent_summary = []
    for idx in range(max(returns.shape[1] - 1, 0)):
        series = adjacent[:, idx] if adjacent.size else np.array([], dtype=float)
        adjacent_summary.append({
            'from_group': idx,
            'to_group': idx + 1,
            'mean_spread': _safe_float(np.nanmean(series)) if series.size else None,
            'positive_ratio': _safe_float(np.mean(series > 0)) if series.size else None,
        })

    return {
        'period_count': int(returns.shape[0]),
        'comparable_period_count': int(comparable.shape[0]),
        'mean_non_empty_group_count': _safe_float(np.mean(non_empty_counts)) if non_empty_counts.size else None,
        'full_group_period_ratio': _safe_float(np.mean(full_rows)) if full_rows.size else None,
        'monotonic_period_ratio': _safe_float(np.mean(monotonic_rows)) if monotonic_rows.size else None,
        'descending_period_ratio': _safe_float(np.mean(np.all(np.diff(comparable, axis=1) <= 0, axis=1))) if comparable.size else None,
        'mean_rank_correlation': _safe_float(np.mean(rank_corrs)) if rank_corrs else None,
        'top_bottom': {
            'mean_spread': _safe_float(np.nanmean(top_bottom)) if top_bottom.size else None,
            'positive_ratio': _safe_float(np.mean(top_bottom > 0)) if top_bottom.size else None,
            'series': spread_series,
        },
        'monotonic_series': monotonic_series,
        'adjacent_spreads': adjacent_summary,
    }
