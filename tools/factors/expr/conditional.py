# =============================================================================
# tools/factors/expr/conditional.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

from typing import Any, List

import numpy as np
import pandas as pd

from .core import FactorExpr
from .leaf import _to_expr
from .operands import OperandExpr
from .pointwise import broadcast_series_to_frame


def _as_frame(value: Any, template: pd.DataFrame) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.reindex(index=template.index, columns=template.columns)
    if isinstance(value, pd.Series):
        return pd.DataFrame(
            broadcast_series_to_frame(template, value),
            index=template.index,
            columns=template.columns,
        )
    return value


def _as_series(value: Any, template: pd.Series) -> Any:
    if isinstance(value, pd.Series):
        return value.reindex(template.index)
    if isinstance(value, pd.DataFrame):
        return value.iloc[:, 0].reindex(template.index)
    return value


def apply_where(condition: Any, true_value: Any, false_value: Any) -> Any:
    """Apply FactorExpr conditional semantics without losing pandas labels."""
    frame = next(
        (
            value
            for value in (true_value, condition, false_value)
            if isinstance(value, pd.DataFrame)
        ),
        None,
    )
    if frame is not None:
        condition_frame = _as_frame(condition, frame)
        if not isinstance(condition_frame, pd.DataFrame):
            condition_frame = pd.DataFrame(
                bool(condition_frame),
                index=frame.index,
                columns=frame.columns,
            )
        true_frame = _as_frame(true_value, frame)
        if not isinstance(true_frame, pd.DataFrame):
            true_frame = pd.DataFrame(
                true_frame,
                index=frame.index,
                columns=frame.columns,
            )
        return true_frame.where(
            condition_frame.astype(bool),
            other=_as_frame(false_value, frame),
        )

    series = next(
        (
            value
            for value in (true_value, condition, false_value)
            if isinstance(value, pd.Series)
        ),
        None,
    )
    if series is not None:
        condition_series = _as_series(condition, series)
        if not isinstance(condition_series, pd.Series):
            condition_series = pd.Series(bool(condition_series), index=series.index)
        true_series = _as_series(true_value, series)
        if not isinstance(true_series, pd.Series):
            true_series = pd.Series(true_series, index=series.index)
        return true_series.where(
            condition_series.astype(bool),
            other=_as_series(false_value, series),
        )

    if all(np.isscalar(value) for value in (condition, true_value, false_value)):
        return true_value if bool(condition) else false_value
    return np.where(condition, true_value, false_value)

class WhereOp(OperandExpr):
    """
    where(cond, a, b)

    Used for research-style universe filtering:
      Final = CCS.where(Illiq <= Illiq.cs_quantile(0.5), np.nan)

    Broadcast rules:
      - Panel(DataFrame) where TimeSeries(Series[bool]) → broadcast by index (axis=0)
      - Panel(DataFrame) where TimeSeries(Series) for `b` → broadcast by index (axis=0)
    """

    def _apply_op(self, values: List[Any]) -> Any:
        return apply_where(*values)


def where(condition: Any, true_value: Any, false_value: Any = np.nan) -> FactorExpr:
    """Build a typed conditional expression from values or FactorExpr nodes."""
    return WhereOp(
        "where",
        _to_expr(condition),
        _to_expr(true_value),
        _to_expr(false_value),
    )
