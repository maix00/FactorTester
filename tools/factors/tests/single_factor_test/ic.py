"""IC test core utilities."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

import numpy as np
import pandas as pd

from tools.factors import Factor
from tools.factors.tests import CrossSectionIC
from tools.factors.FactorTester import _align_ts
from tools.data.types import DataFreq
from tools.data.types import finest_index


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
    acf_vals = None
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

    # 把完整的 acf 数组也缓存起来，避免 _build_ic_response 重复计算
    acf_vals_list = acf_vals.tolist() if acf_vals is not None else None

    return pd.Series({
        "mean": mean,
        "std": std,
        "IR": ir,
        "t_stat": t_stat,
        "max": max_ic,
        "min": min_ic,
        "ac1": ac1,
        "half_life": half_life,
        "acf_vals": acf_vals_list,
    })


def run_ic_for_factor(
    tester: Any,
    params: Dict[str, Any],
    factor_list: List[Factor],
) -> Tuple[List[Factor], pd.Series, pd.Series, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run CrossSectionIC and return IC stats, FE/RE intermediates, and their source mask."""
    ic_family_cls = params.get('_ic_family_cls') or CrossSectionIC
    clean_params = {k: v for k, v in params.items() if not str(k).startswith('_')}
    ic_family = ic_family_cls()
    ic_factor = ic_family.get_factor(**clean_params)
    ic_factor.clear()

    try:
        sample_factor = factor_list[0]
        source_freq = sample_factor._source_freq
        if source_freq is None:
            configured_source_freq = getattr(getattr(sample_factor, "family", None), "_source_freq", None)
            source_freq = DataFreq(configured_source_freq) if configured_source_freq else None
        ic_factor.evaluate(tester.products, freq=source_freq)

        ic_series = cast(pd.Series, ic_factor.table["IC"])
        if not isinstance(ic_series, pd.Series):
            ic_series = cast(pd.Series, pd.Series(ic_series))

        if tester.start_date is not None and len(ic_series) > 0:
            idx_ts = finest_index(ic_series.index)
            ref_ts = idx_ts[0] if len(idx_ts) > 0 else pd.Timestamp(tester.start_date)
            ic_series = cast(pd.Series, ic_series[idx_ts >= _align_ts(pd.Timestamp(tester.start_date), ref_ts)])
        if tester.end_date is not None and len(ic_series) > 0:
            idx_ts = finest_index(ic_series.index)
            ref_ts = idx_ts[0] if len(idx_ts) > 0 else pd.Timestamp(tester.end_date)
            ic_series = cast(pd.Series, ic_series[idx_ts <= _align_ts(pd.Timestamp(tester.end_date), ref_ts)])

        re_table = ic_factor.get_intermediate("RE")
        fe_table = ic_factor.get_intermediate("FE")
        stats = ic_stats(ic_series)

        re_table = re_table.copy() if re_table is not None else pd.DataFrame()
        fe_table = fe_table.copy() if fe_table is not None else pd.DataFrame()
        ic_run_result = tester._get_result(ic_factor)
        data_present_mask = ic_run_result.data_present_mask.copy(deep=False)

        return (
            factor_list, ic_series.copy(), cast(pd.Series, stats),
            cast(pd.DataFrame, re_table), cast(pd.DataFrame, fe_table),
            cast(pd.DataFrame, data_present_mask),
        )
    finally:
        if hasattr(tester, "discard_result"):
            tester.discard_result(ic_factor)
        else:
            ic_factor.clear()
