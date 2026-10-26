"""Futures term-structure operators for the public factor API."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FactorExpr

DAYS = "DAYS_TO_MATURITY"
RANK = "TERM_RANK"
PAIR = {
    "term_spread", "term_ratio", "term_log_ratio", "term_contango",
    "term_carry_annualized", "term_slope_segment",
}
DEPTH = {"term_slope", "term_curvature"}


def _value(curve: pd.DataFrame, rank: int, column: str) -> float:
    if len(curve) <= rank:
        return float("nan")
    return float(curve.iloc[rank][column])


def _metric(op: str, curve: pd.DataFrame, *, near_rank: int, far_rank: int,
            depth: int, column: str) -> float:
    if curve.empty or column not in curve.columns:
        return float("nan")
    curve = curve.sort_values(RANK).reset_index(drop=True) if RANK in curve.columns else curve.reset_index(drop=True)
    if op in PAIR:
        near, far = _value(curve, near_rank, column), _value(curve, far_rank, column)
        if op == "term_spread":
            return near - far
        if op == "term_ratio":
            return near / far - 1.0 if far else float("nan")
        if op == "term_log_ratio":
            return float(np.log(near / far)) if near > 0 and far > 0 else float("nan")
        if op == "term_contango":
            return far / near - 1.0 if near else float("nan")
        if DAYS not in curve.columns or len(curve) <= max(near_rank, far_rank):
            return float("nan")
        days = float(curve.iloc[far_rank][DAYS]) - float(curve.iloc[near_rank][DAYS])
        if not np.isfinite(days) or days == 0:
            return float("nan")
        if op == "term_carry_annualized":
            return (near / far - 1.0) * 365.0 / days if far else float("nan")
        return (far - near) / days
    if op == "term_rank_value":
        return _value(curve, near_rank, column)
    if op in DEPTH:
        if DAYS not in curve.columns:
            return float("nan")
        frame = curve.head(depth)[[DAYS, column]].dropna()
        if len(frame) < (2 if op == "term_slope" else 3):
            return float("nan")
        return float(np.polyfit(frame[DAYS].to_numpy(float), frame[column].to_numpy(float), 1 if op == "term_slope" else 2)[0])
    raise ValueError(f"unknown term operation {op}")


def evaluate_term_metric(op: str, curve: pd.DataFrame, *, near_rank: int,
                         far_rank: int, depth: int, column: str) -> float:
    """Public pure-metric entry point shared with tools.factors."""
    return _metric(op, curve, near_rank=near_rank, far_rank=far_rank,
                   depth=depth, column=column)


class TermStructureExpr(FactorExpr):
    def __init__(self, op: str, *, near_rank: int = 0, far_rank: int = 1,
                 depth: int = 4, column: str = "CLOSE"):
        if op not in PAIR | DEPTH | {"term_rank_value"}:
            raise ValueError(f"unknown term operation {op}")
        self.op = op
        self.near_rank = near_rank
        self.far_rank = far_rank
        self.depth = depth
        self.column = column

    def _structural_key(self):
        return ("alpha.factor.TermStructureExpr", self.op, self.near_rank,
                self.far_rank, self.depth, self.column)

    def evaluate(self, ctx) -> pd.DataFrame:
        curves = getattr(ctx, "term_curves", None) or {}
        index = next(iter(ctx.preloaded.values())).index if ctx.preloaded else pd.RangeIndex(0)
        timestamps = index.as_unit("ns").asi8 if isinstance(index, pd.DatetimeIndex) else None
        out = {}
        for product in ctx.products:
            curve = curves.get(product)
            values = np.full(len(index), np.nan, dtype=float)
            if isinstance(curve, (tuple, list)) and curve:
                for row, timestamp in enumerate(timestamps if timestamps is not None else [None] * len(index)):
                    active = [
                        item for item in curve
                        if getattr(item, "available_at_ns", None) is None
                        or timestamp is None or item.available_at_ns <= timestamp
                    ]
                    if active:
                        selected = active[-1]
                        values[row] = _metric(
                            self.op, pd.DataFrame(selected.rows()), near_rank=self.near_rank,
                            far_rank=self.far_rank, depth=self.depth, column=self.column,
                        )
            elif curve is not None:
                values.fill(_metric(
                    self.op, pd.DataFrame(curve.rows() if hasattr(curve, "rows") else curve),
                    near_rank=self.near_rank, far_rank=self.far_rank,
                    depth=self.depth, column=self.column,
                ))
            out[product] = values
        return pd.DataFrame(out, index=index)


def _make(op):
    return lambda *, near_rank=0, far_rank=1, column="CLOSE", **kwargs: TermStructureExpr(
        op, near_rank=near_rank, far_rank=far_rank, column=column, **kwargs,
    )


term_spread = _make("term_spread")
term_ratio = _make("term_ratio")
term_log_ratio = _make("term_log_ratio")
term_contango = _make("term_contango")
term_carry_annualized = _make("term_carry_annualized")
term_slope_segment = _make("term_slope_segment")
term_slope = lambda *, depth=4, column="CLOSE": TermStructureExpr("term_slope", depth=depth, column=column)
term_curvature = lambda *, depth=4, column="CLOSE": TermStructureExpr("term_curvature", depth=depth, column=column)
term_rank_value = lambda *, rank=0, column="CLOSE": TermStructureExpr("term_rank_value", near_rank=rank, column=column)
