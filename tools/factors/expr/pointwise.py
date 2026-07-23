"""Shared pointwise execution kernels for batch and incremental FactorExpr.

This module owns numerical semantics only.  Author-facing names, LaTeX, arity,
and aliases remain in :mod:`tools.factors.expr.composite`.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd


POINTWISE_OPS = frozenset({
    "add", "sub", "mul", "div",
    "neg", "abs", "sign", "sqrt", "log", "tanh",
    "pow", "bimax", "bimin", "max", "min",
    "gt", "lt", "ge", "le", "eq", "ne",
    "and", "or", "not",
})


def broadcast_series_to_frame(frame: pd.DataFrame, series: pd.Series) -> np.ndarray:
    """Broadcast a time-indexed Series across a panel's product columns."""
    if not frame.index.equals(series.index):
        series = series.reindex(frame.index)
    return series.to_numpy(dtype=float)[:, np.newaxis]


def align_series(left: pd.Series, right: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Align two time series on their shared observations."""
    if left.index.equals(right.index):
        return left, right
    common = left.index.intersection(right.index)
    return left.loc[common], right.loc[common]


def apply_binary(left: Any, right: Any, op: str) -> Any:
    """Apply a binary operation with FactorExpr's time-axis broadcasting."""
    if isinstance(left, pd.DataFrame) and isinstance(right, pd.Series):
        if op in {"and", "or"}:
            right_frame = pd.DataFrame(
                broadcast_series_to_frame(left, right).astype(bool),
                index=left.index,
                columns=left.columns,
            )
            return left.astype(bool) & right_frame if op == "and" else left.astype(bool) | right_frame
        return getattr(left, op)(right, axis=0)

    if isinstance(left, pd.Series) and isinstance(right, pd.DataFrame):
        if op in {"and", "or"}:
            left_frame = pd.DataFrame(
                broadcast_series_to_frame(right, left).astype(bool),
                index=right.index,
                columns=right.columns,
            )
            return left_frame & right.astype(bool) if op == "and" else left_frame | right.astype(bool)
        reverse = {
            "sub": "rsub",
            "div": "rdiv",
            "gt": "lt",
            "lt": "gt",
            "ge": "le",
            "le": "ge",
        }.get(op)
        if reverse is not None:
            return getattr(right, reverse)(left, axis=0)
        return getattr(right, op)(left, axis=0)

    if isinstance(left, pd.Series) and isinstance(right, pd.Series):
        left, right = align_series(left, right)

    if op == "add":
        return left + right
    if op == "sub":
        return left - right
    if op == "mul":
        return left * right
    if op == "div":
        return left / right
    if op == "gt":
        return left > right
    if op == "lt":
        return left < right
    if op == "ge":
        return left >= right
    if op == "le":
        return left <= right
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "and":
        if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
            return np.asarray(left).astype(bool) & np.asarray(right).astype(bool)
        return left & right
    if op == "or":
        if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
            return np.asarray(left).astype(bool) | np.asarray(right).astype(bool)
        return left | right
    raise ValueError(f"unsupported binary pointwise op: {op}")


def _apply_extreme(left: Any, right: Any, *, maximum: bool) -> Any:
    func = np.maximum if maximum else np.minimum
    clip_arg = "lower" if maximum else "upper"

    if isinstance(left, pd.DataFrame) and isinstance(right, pd.Series):
        return pd.DataFrame(
            func(left.values, broadcast_series_to_frame(left, right)),
            index=left.index,
            columns=left.columns,
        )
    if isinstance(left, pd.Series) and isinstance(right, pd.DataFrame):
        return pd.DataFrame(
            func(broadcast_series_to_frame(right, left), right.values),
            index=right.index,
            columns=right.columns,
        )
    if isinstance(left, pd.Series) and isinstance(right, pd.Series):
        aligned_left, aligned_right = align_series(left, right)
        return pd.Series(
            func(aligned_left.values, aligned_right.values),
            index=aligned_left.index,
        )
    if isinstance(left, pd.DataFrame) and np.isscalar(right):
        return left.clip(**{clip_arg: right})
    if isinstance(right, pd.DataFrame) and np.isscalar(left):
        return right.clip(**{clip_arg: left})
    if not isinstance(left, (pd.DataFrame, pd.Series)) and not isinstance(
        right, (pd.DataFrame, pd.Series)
    ):
        return func(left, right)
    return pd.DataFrame(
        func(left.values, right.values),
        index=left.index,
        columns=left.columns,
    )


def apply_pointwise(op: str, values: Sequence[Any]) -> Any:
    """Execute one registered pointwise operation on evaluated operands."""
    if op not in POINTWISE_OPS:
        raise ValueError(f"unsupported pointwise op: {op}")

    if op in {
        "add", "sub", "mul", "div",
        "gt", "lt", "ge", "le", "eq", "ne", "and", "or",
    }:
        return apply_binary(values[0], values[1], op)
    if op == "neg":
        return -values[0]
    if op == "abs":
        return abs(values[0])
    if op == "sign":
        return np.sign(values[0])
    if op == "sqrt":
        return np.sqrt(values[0])
    if op == "log":
        return np.log(values[0])
    if op == "tanh":
        return np.tanh(values[0])
    if op == "pow":
        return values[0] ** values[1]
    if op == "not":
        value = values[0]
        if hasattr(value, "astype"):
            return ~value.astype(bool)
        return not bool(value)
    if op in {"bimax", "bimin", "max", "min"}:
        maximum = op in {"bimax", "max"}
        result = values[0]
        for value in values[1:]:
            result = _apply_extreme(result, value, maximum=maximum)
        return result
    raise ValueError(f"unsupported pointwise op: {op}")
