"""Edge cases for the scalar truncated groupby arg-extreme path."""

from __future__ import annotations

import numpy as np
import pytest

from tools.factors.expr.groupby_scope_eval import _prefix_arg_extreme_loop


@pytest.mark.parametrize("operation", ["argmax", "argmin"])
def test_truncated_arg_extreme_keeps_ties_missing_and_infinities(operation: str) -> None:
    rng = np.random.default_rng(423_15)
    values = rng.integers(-4, 5, size=4096).astype(float)
    values[2:8] = [np.nan, 3.0, 3.0, np.inf, -np.inf, np.nan]
    start, end = 2, 7

    actual = _prefix_arg_extreme_loop(values, operation, start, end)
    expected = np.full(len(values), np.nan)
    for position in range(start, len(values)):
        if np.isnan(values[position]):
            continue
        limit = min(position, end)
        candidates = values[start:limit + 1]
        valid = np.flatnonzero(~np.isnan(candidates))
        if valid.size == 0:
            best = start
        else:
            finite_candidates = candidates[valid]
            extreme = (
                np.max(finite_candidates)
                if operation == "argmax"
                else np.min(finite_candidates)
            )
            best = start + int(valid[np.flatnonzero(finite_candidates == extreme)[0]])
        span = position - start
        expected[position] = 0.0 if span == 0 else (position - best) / span

    np.testing.assert_allclose(actual, expected, equal_nan=True)
