"""Shared term-structure curve calculations for batch and live FactorExpr."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tools.products.AdjustableTermStructure import (
    TERM_DAYS_TO_MATURITY_COL,
    TERM_RANK_COL,
)


PAIR_TERM_STRUCTURE_OPS = frozenset({
    "term_spread",
    "term_ratio",
    "term_log_ratio",
    "term_contango",
    "term_carry_annualized",
    "term_slope_segment",
})
DEPTH_TERM_STRUCTURE_OPS = frozenset({"term_slope", "term_curvature"})
RANK_TERM_STRUCTURE_OPS = frozenset({"term_rank_value"})


def normalize_term_curve(curve: Any) -> pd.DataFrame:
    if isinstance(curve, pd.DataFrame):
        frame = curve.copy()
    else:
        frame = pd.DataFrame(curve)
    if frame.empty:
        return frame
    if TERM_RANK_COL in frame.columns:
        frame = frame.sort_values(TERM_RANK_COL)
    return frame.reset_index(drop=True)


def evaluate_term_curve(
    op: str,
    curve: pd.DataFrame,
    *,
    near_rank: int,
    far_rank: int,
    depth: int,
    column: str,
) -> float:
    curve = normalize_term_curve(curve)
    if curve.empty:
        return float("nan")
    if column not in curve.columns:
        raise KeyError(f"{column!r} not in term structure curve")

    if op in PAIR_TERM_STRUCTURE_OPS:
        max_rank = max(int(near_rank), int(far_rank))
        if len(curve) <= max_rank:
            return float("nan")
        near = _curve_value(curve, near_rank, column)
        far = _curve_value(curve, far_rank, column)
        if op == "term_spread":
            return near - far
        if op == "term_ratio":
            return near / far - 1.0 if far else float("nan")
        if op == "term_log_ratio":
            return float(np.log(near / far)) if near > 0 and far > 0 else float("nan")
        if op == "term_contango":
            return far / near - 1.0 if near else float("nan")

        _require_days_column(curve)
        near_days = _curve_days(curve, near_rank)
        far_days = _curve_days(curve, far_rank)
        day_diff = far_days - near_days
        if not np.isfinite(day_diff) or day_diff == 0:
            return float("nan")
        if op == "term_carry_annualized":
            return (near / far - 1.0) * 365.0 / day_diff if far else float("nan")
        if op == "term_slope_segment":
            return (far - near) / day_diff

    if op in RANK_TERM_STRUCTURE_OPS:
        return _curve_value(curve, near_rank, column)

    _require_days_column(curve)
    frame = curve.head(int(depth))[[TERM_DAYS_TO_MATURITY_COL, column]].dropna()
    if op == "term_slope":
        if len(frame) < 2:
            return float("nan")
        return float(np.polyfit(_days(frame), _values(frame, column), 1)[0])
    if op == "term_curvature":
        if len(frame) < 3:
            return float("nan")
        return float(np.polyfit(_days(frame), _values(frame, column), 2)[0])
    raise ValueError(f"Unknown term structure op: {op}")


def _curve_value(curve: pd.DataFrame, rank: int, column: str) -> float:
    if curve.empty or len(curve) <= int(rank):
        return float("nan")
    return float(curve.iloc[int(rank)][column])


def _curve_days(curve: pd.DataFrame, rank: int) -> float:
    if curve.empty or len(curve) <= int(rank):
        return float("nan")
    return float(curve.iloc[int(rank)][TERM_DAYS_TO_MATURITY_COL])


def _require_days_column(curve: pd.DataFrame) -> None:
    if TERM_DAYS_TO_MATURITY_COL not in curve.columns:
        raise KeyError(f"{TERM_DAYS_TO_MATURITY_COL!r} not in term structure curve")


def _days(frame: pd.DataFrame) -> np.ndarray:
    return frame[TERM_DAYS_TO_MATURITY_COL].to_numpy(dtype=float)


def _values(frame: pd.DataFrame, column: str) -> np.ndarray:
    return frame[column].to_numpy(dtype=float)
