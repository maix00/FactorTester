"""Detail analytics for one group from the latest group-test run."""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from tools.factors.FactorTester import _signal_time
from tools.products.product_utils import product_display_name


def build_group_detail(
    group_index: int,
    products_by_group: dict,
    group_returns_np: np.ndarray,
    index_list: list,
    metrics: dict | None = None,
) -> dict[str, Any]:
    returns = np.asarray(group_returns_np[:, group_index], dtype=float)
    clean_returns = returns[np.isfinite(returns)]
    group_products = products_by_group.get(group_index, {})
    total_periods = max(len(index_list), 1)

    entry_counts = Counter()
    product_display_map = {}
    for products in group_products.values():
        for product in products:
            display = product_display_name(product)
            entry_counts.update([display['name']])
            product_display_map[display['name']] = display
    entry_frequency = [
        {
            'product': product_display_map.get(product, {'name': product, 'desc': product}),
            'count': count,
            'frequency': count / total_periods,
        }
        for product, count in entry_counts.most_common()
    ]

    periods = []
    cumulative_return = 1.0
    return_series = []
    for row_idx, idx_entry in enumerate(index_list):
        value = returns[row_idx]
        if not np.isfinite(value):
            continue
        cumulative_return *= 1.0 + float(value)
        return_series.append({
            'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
            'return': float(value),
            'cumulative_return': cumulative_return,
        })
        periods.append({
            'timestamp': pd.Timestamp(_signal_time(idx_entry)).isoformat(),
            'return': float(value),
            'products': [product_display_name(product) for product in group_products.get(idx_entry, [])],
        })
    periods_desc = sorted(periods, key=lambda item: item['return'], reverse=True)
    positive_run_analysis = _build_positive_run_analysis(return_series)

    if clean_returns.size:
        hist_counts, hist_edges = np.histogram(clean_returns, bins=min(20, max(5, int(np.sqrt(clean_returns.size)))))
        histogram = [
            {
                'left': float(hist_edges[idx]),
                'right': float(hist_edges[idx + 1]),
                'count': int(count),
            }
            for idx, count in enumerate(hist_counts)
        ]
        quantiles = {
            key: float(value)
            for key, value in zip(
                ('p05', 'p25', 'p50', 'p75', 'p95'),
                np.quantile(clean_returns, [0.05, 0.25, 0.50, 0.75, 0.95]),
            )
        }
    else:
        histogram = []
        quantiles = {}

    return {
        'group_index': group_index,
        'summary': metrics or {},
        'entry_frequency': entry_frequency,
        'top_periods': periods_desc[:10],
        'bottom_periods': list(reversed(periods_desc[-10:])),
        'distribution': {
            'histogram': histogram,
            'quantiles': quantiles,
            'period_count': int(clean_returns.size),
        },
        'return_series': return_series,
        'positive_run_analysis': positive_run_analysis,
    }


def _build_positive_run_analysis(return_series: list[dict[str, Any]]) -> dict[str, Any]:
    runs = []
    current = []
    for row in return_series:
        if row['return'] > 0:
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    positive_runs = []
    for rows in runs:
        run_return = float(np.prod([1.0 + row['return'] for row in rows]) - 1.0)
        positive_runs.append({
            'start': rows[0]['timestamp'],
            'end': rows[-1]['timestamp'],
            'period_count': len(rows),
            'return': run_return,
        })
    positive_runs.sort(key=lambda item: item['return'], reverse=True)

    total_positive_run_return = sum(max(item['return'], 0.0) for item in positive_runs)
    top1 = positive_runs[:1]
    top3 = positive_runs[:3]

    def _without(selected: list[dict[str, Any]]) -> float:
        excluded = {(item['start'], item['end']) for item in selected}
        wealth = 1.0
        in_excluded = False
        current_key = None
        for row in return_series:
            row_ts = row['timestamp']
            if not in_excluded:
                for key in excluded:
                    if row_ts == key[0]:
                        in_excluded = True
                        current_key = key
                        break
            if in_excluded and current_key is not None:
                if row_ts == current_key[1]:
                    in_excluded = False
                    current_key = None
                continue
            wealth *= 1.0 + row['return']
        return wealth - 1.0

    top1_ratio = (top1[0]['return'] / total_positive_run_return) if (top1 and total_positive_run_return > 0) else None
    top3_ratio = (sum(item['return'] for item in top3) / total_positive_run_return) if total_positive_run_return > 0 else None
    without_top1 = _without(top1) if top1 else None
    without_top3 = _without(top3) if top3 else None
    concentrated = bool(
        (top1_ratio is not None and top1_ratio >= 0.5 and without_top1 is not None and without_top1 <= 0)
        or (top3_ratio is not None and top3_ratio >= 0.8 and without_top3 is not None and without_top3 <= 0)
    )
    return {
        'run_count': len(positive_runs),
        'top_runs': positive_runs[:5],
        'top1_positive_contribution_ratio': top1_ratio,
        'top3_positive_contribution_ratio': top3_ratio,
        'return_without_top1_run': without_top1,
        'return_without_top3_runs': without_top3,
        'is_concentrated': concentrated,
    }
