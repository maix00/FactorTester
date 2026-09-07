"""IC test core utilities."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

import numpy as np
import pandas as pd

from tools.factors import Factor
from tools.factors.tester_calc import CrossSectionIC
from tools.factors.FactorTester import _align_ts
from tools.data.types import DataFreq
from tools.data.types import finest_index
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    expected_sign_for_factor,
    summarize_ic_series,
)
from tools.factors.temporal_support import temporal_support_for_ic


# A forward label is allowed to read data after the user-selected signal
# window.  The extra calendar buffer is intentional: a physical DAY1 label
# may cross a weekend or an exchange holiday (for example the Chinese New
# Year break), so adding only exactly one calendar day is not sufficient to
# reach the next trading session.  The resulting IC series is still clipped
# back to ``tester.end_dt`` by ``collect_ic_result``.
IC_FORWARD_LABEL_CALENDAR_BUFFER = pd.Timedelta(days=14)


def ic_stats(
    ic_series: pd.Series,
    *,
    expected_sign: int | None = None,
    expected_sign_source: str | None = None,
    temporal_support: Any | None = None,
) -> pd.Series:
    """Return explicit IC diagnostics plus documented compatibility aliases."""

    return pd.Series(
        summarize_ic_series(
            ic_series,
            expected_sign=expected_sign,
            expected_sign_source=expected_sign_source,
            temporal_support=temporal_support,
        )
    )


def run_ic_for_factor(
    tester: Any,
    params: Dict[str, Any],
    factor_list: List[Factor],
) -> Tuple[List[Factor], pd.Series, pd.Series, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run CrossSectionIC and return IC stats, FE/RE intermediates, and their source mask."""
    ic_factor, source_freq = build_ic_factor(params, factor_list)
    temporal_support = _temporal_support_for_ic_params(params, factor_list)
    expected_sign, expected_sign_source = expected_sign_for_factor(factor_list[0]) if factor_list else (None, None)
    try:
        evaluation_end_dt = ic_evaluation_end_dt(tester, temporal_support)
        evaluate_kwargs: Dict[str, Any] = {
            "freq": source_freq,
            "start_dt": tester.start_dt,
            "end_dt": evaluation_end_dt,
        }
        warmup_seconds = (
            temporal_support.factor_input_support_seconds
            if temporal_support is not None else None
        )
        # A known zero-support leaf does not need an explicit zero expansion;
        # omitting it preserves the narrow evaluator contract used by tests and
        # lightweight callers.  Positive support is always passed through.
        if warmup_seconds is not None and warmup_seconds > 0:
            evaluate_kwargs["warmup_window"] = pd.Timedelta(seconds=warmup_seconds)
        ic_factor.evaluate(tester.products, **evaluate_kwargs)
        return collect_ic_result(
            tester,
            ic_factor,
            factor_list,
            temporal_support=temporal_support,
            expected_sign=expected_sign,
            expected_sign_source=expected_sign_source,
        )
    finally:
        discard_ic_factor(tester, ic_factor)


def ic_evaluation_end_dt(tester: Any, temporal_support: Any | None = None) -> Any:
    """Return the raw-data end boundary needed to form forward IC labels.

    ``tester.end_dt`` is the user's signal/output boundary.  A forward-return
    expression also needs observations after that boundary, otherwise every
    signal near the end of the requested sample is silently dropped.  Keep the
    extension local to IC evaluation; result collection continues to clip the
    IC series to the requested signal window.
    """
    end_dt = getattr(tester, "end_dt", None)
    if end_dt is None or not getattr(end_dt, "is_set", False):
        return end_dt
    label_seconds = getattr(temporal_support, "label_horizon_seconds", None)
    try:
        label_seconds = float(label_seconds)
    except (TypeError, ValueError):
        label_seconds = 0.0
    if not np.isfinite(label_seconds) or label_seconds <= 0:
        return end_dt
    from tools.data.types import DataTime

    extension = pd.Timedelta(seconds=label_seconds) + IC_FORWARD_LABEL_CALENDAR_BUFFER
    return DataTime(
        ts=pd.Timestamp(end_dt.ts) + extension,
        precision=getattr(end_dt, "precision", "exact"),
        tz=getattr(end_dt, "tz", None),
    )


def build_ic_factor(params: Dict[str, Any], factor_list: List[Factor]) -> tuple[Factor, DataFreq | None]:
    """Build one IC root without evaluating it, for batch schedulers."""
    ic_family_cls = params.get('_ic_family_cls') or CrossSectionIC
    clean_params = {k: v for k, v in params.items() if not str(k).startswith('_')}
    ic_family = ic_family_cls()
    ic_factor = ic_family.get_factor(**clean_params)
    ic_factor.clear()

    sample_factor = factor_list[0]
    source_freq = sample_factor._source_freq
    if source_freq is None:
        configured_source_freq = getattr(getattr(sample_factor, "family", None), "_source_freq", None)
        source_freq = DataFreq(configured_source_freq) if configured_source_freq else None
    return ic_factor, source_freq


def _temporal_support_for_ic_params(
    params: Dict[str, Any], factor_list: List[Factor],
) -> Any | None:
    """Build the explicit IC contract without interpreting an alias string."""

    if not factor_list:
        return None
    try:
        lag = int(params.get("Lag", 0) or 0)
    except (TypeError, ValueError):
        lag = 0
    return temporal_support_for_ic(
        factor_list[0],
        returns_factor=params.get("RE"),
        lag=lag,
    )


def annotate_ic_temporal_support(
    tester: Any,
    ic_factor: Factor,
    factor_list: List[Factor],
    stats: pd.Series,
    temporal_support: Any | None,
    *,
    ic_series: pd.Series | None = None,
    expected_sign: int | None = None,
    expected_sign_source: str | None = None,
) -> pd.Series:
    """Attach a non-numeric temporal contract to IC stats and lifecycle results."""

    if temporal_support is None:
        return stats
    annotated = (
        pd.Series(
            summarize_ic_series(
                ic_series,
                expected_sign=expected_sign,
                expected_sign_source=expected_sign_source,
                temporal_support=temporal_support,
            )
        )
        if ic_series is not None else stats.copy()
    )
    annotated["temporal_support"] = temporal_support.to_dict()
    annotated["temporal_support_status"] = temporal_support.support_status
    targets: list[Any] = [ic_factor, *factor_list]
    seen: set[int] = set()
    for factor in targets:
        if id(factor) in seen:
            continue
        seen.add(id(factor))
        try:
            result = tester._get_result(factor)
        except (KeyError, TypeError, AttributeError):
            continue
        if hasattr(result, "temporal_support"):
            result.temporal_support = temporal_support
        if hasattr(result, "hac_diagnostics"):
            result.hac_diagnostics = None
    return annotated


def collect_ic_result(
    tester: Any, ic_factor: Factor, factor_list: List[Factor],
    *, temporal_support: Any | None = None,
    expected_sign: int | None = None,
    expected_sign_source: str | None = None,
) -> Tuple[List[Factor], pd.Series, pd.Series, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Extract an already evaluated IC root's data and summary statistics."""
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
    stats = ic_stats(
        ic_series,
        expected_sign=expected_sign,
        expected_sign_source=expected_sign_source,
        temporal_support=temporal_support,
    )
    rank_panels = {
        key: getattr(ic_factor, "table", pd.DataFrame()).attrs.get(key)
        for key in ("factor_cs_rank", "return_cs_rank")
    }
    stats = annotate_ic_temporal_support(
        tester,
        ic_factor,
        factor_list,
        stats,
        temporal_support,
        ic_series=ic_series,
        expected_sign=expected_sign,
        expected_sign_source=expected_sign_source,
    )
    for key, panel in rank_panels.items():
        if isinstance(panel, pd.DataFrame):
            stats.attrs[key] = panel

    re_table = re_table.copy() if re_table is not None else pd.DataFrame()
    fe_table = fe_table.copy() if fe_table is not None else pd.DataFrame()
    ic_run_result = tester._get_result(ic_factor)
    data_present_mask = ic_run_result.data_present_mask.copy(deep=False)

    # Own exactly one copy before the evaluated root is cleared.  The merge
    # layer keeps this object by reference; copying again there doubled peak
    # memory for every long high-frequency root.
    ic_series = ic_series.copy()
    return (
        factor_list, ic_series, cast(pd.Series, stats),
        cast(pd.DataFrame, re_table), cast(pd.DataFrame, fe_table),
        cast(pd.DataFrame, data_present_mask),
    )


def discard_ic_factor(tester: Any, ic_factor: Factor) -> None:
    if hasattr(tester, "discard_result"):
        tester.discard_result(ic_factor)
    else:
        ic_factor.clear()
