"""Edge cases for the scalar truncated groupby arg-extreme path."""

from __future__ import annotations

import numpy as np
import pytest

from tests.factors._scope_extrema_oracle import _prefix_arg_extreme_loop


@pytest.mark.parametrize("operation", ["argmax", "argmin"])
def test_truncated_arg_extreme_keeps_ties_missing_and_infinities(operation: str) -> None:
    rng = np.random.default_rng(423_15)
    values = rng.integers(-4, 5, size=4096).astype(float)
    values[2:8] = [np.nan, 3.0, 3.0, np.inf, -np.inf, np.nan]
    start, end = 2, 7

    actual = _prefix_arg_extreme_loop(values, operation, start, end)
    expected = np.full(len(values), np.nan)
    for position in range(start, len(values)):
        limit = min(position, end)
        candidates = values[start:limit + 1]
        valid = np.flatnonzero(~np.isnan(candidates))
        if valid.size == 0:
            continue
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


@pytest.mark.parametrize("values,start,end,expected", [
    ([np.nan, 1, 2], 0, 0, [np.nan, np.nan, np.nan]),
    ([1, 2, 3], 2, 1, [np.nan, np.nan, np.nan]),
    ([1, np.nan, 2], 0, None, [0, 1, 0]),
    ([1, 5, 5, np.nan], 0, 2, [0, 0, .5, 2/3]),
    ([1, np.inf, 4], 0, None, [0, 0, .5]),
])
def test_oracle_hand_computed_contract(values, start, end, expected):
    np.testing.assert_allclose(_prefix_arg_extreme_loop(values, "argmax", start, end), expected, equal_nan=True)


def test_oracle_nan_policy_only_checks_candidates():
    values = [1, np.nan, 2, np.nan]
    np.testing.assert_allclose(_prefix_arg_extreme_loop(values, "argmax", 0, 2, min_periods=2),
                               [np.nan, np.nan, 0, 1/3], equal_nan=True)
    assert np.isnan(_prefix_arg_extreme_loop(values, "argmax", 0, 2, propagate_nan=True)[-1])
