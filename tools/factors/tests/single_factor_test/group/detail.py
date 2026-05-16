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
    }
