"""IC test core utilities."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

import numpy as np
import pandas as pd

from tools.factors import CrossSectionIC, Factor
from tools.factors.FactorTester import _align_ts


def ic_stats(ic_series: pd.Series) -> pd.Series:
    """计算 IC 序列的汇总统计量。"""
    mean = ic_series.mean()
    std = ic_series.std()
    ir = mean / std if std != 0 else np.nan
    t_stat = mean / (std / np.sqrt(len(ic_series.dropna()))) if std != 0 and len(ic_series.dropna()) > 1 else np.nan
    max_ic = ic_series.max()
    min_ic = ic_series.min()

    s = ic_series.dropna()
    ac1 = None
    half_life = None
    if len(s) > 2:
        from statsmodels.tsa.stattools import acf
        try:
            nlags = min(20, max(1, len(s) // 2 - 1))
            acf_vals = acf(s.values, nlags=nlags, fft=False)
            ac1 = float(acf_vals[1]) if len(acf_vals) > 1 else None
            for lag in range(1, len(acf_vals)):
                if acf_vals[lag] < 0.5:
                    prev = acf_vals[lag - 1]
                    curr = acf_vals[lag]
                    frac = (0.5 - prev) / (curr - prev) if curr != prev else 0.0
                    half_life = float(lag - 1 + frac)
                    break
            if half_life is None:
                half_life = float("inf")
        except Exception:
            pass

    return pd.Series({
        "mean": mean,
        "std": std,
        "IR": ir,
        "t_stat": t_stat,
        "max": max_ic,
        "min": min_ic,
        "ac1": ac1,
        "half_life": half_life,
    })


def run_ic_for_factor(
    tester: Any,
    params: Dict[str, Any],
    factor_list: List[Factor],
) -> Tuple[List[Factor], pd.Series, pd.Series, pd.DataFrame, pd.DataFrame]:
    """Run CrossSectionIC and return IC series/stats plus raw RE/FE intermediates."""
    ic_family = CrossSectionIC()
    ic_factor = ic_family.get_factor(**params)
    ic_factor.clear()

    sample_factor = factor_list[0]
    ic_factor.evaluate(tester.products, source_freq=sample_factor._source_freq)

    ic_series = cast(pd.Series, ic_factor.table["IC"])
    if not isinstance(ic_series, pd.Series):
        ic_series = cast(pd.Series, pd.Series(ic_series))

    if tester.start_date is not None and len(ic_series) > 0:
        idx_ts = cast(pd.Index, ic_series.index.get_level_values(-1))
        ref_ts = idx_ts[0] if len(idx_ts) > 0 else pd.Timestamp(tester.start_date)
        ic_series = cast(pd.Series, ic_series[idx_ts >= _align_ts(pd.Timestamp(tester.start_date), ref_ts)])
    if tester.end_date is not None and len(ic_series) > 0:
        idx_ts = cast(pd.Index, ic_series.index.get_level_values(-1))
        ref_ts = idx_ts[0] if len(idx_ts) > 0 else pd.Timestamp(tester.end_date)
        ic_series = cast(pd.Series, ic_series[idx_ts <= _align_ts(pd.Timestamp(tester.end_date), ref_ts)])

    re_table = ic_factor.get_intermediate("RE")
    fe_table = ic_factor.get_intermediate("FE")
    import logging
    _log = logging.getLogger(__name__)
    _log.warning("DEBUG re_table index names=%s, shape=%s", re_table.index.names if re_table is not None else 'None', re_table.shape if re_table is not None else 'None')
    _log.warning("DEBUG fe_table index names=%s, shape=%s", fe_table.index.names if fe_table is not None else 'None', fe_table.shape if fe_table is not None else 'None')
    stats = ic_stats(ic_series)

    re_table = re_table.copy() if re_table is not None else pd.DataFrame()
    fe_table = fe_table.copy() if fe_table is not None else pd.DataFrame()

    return factor_list, ic_series, cast(pd.Series, stats), cast(pd.DataFrame, re_table), cast(pd.DataFrame, fe_table)

