"""Shared term-structure curve calculations for batch and live FactorExpr."""

from __future__ import annotations

from typing import Any

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
    """Evaluate through the single public alpha metric implementation."""
    from alpha.factor.term import evaluate_term_metric
    return evaluate_term_metric(
        op, curve, near_rank=near_rank, far_rank=far_rank,
        depth=depth, column=column,
    )
