"""The independent paper oracle must use the selected outer window."""
import numpy as np

from tests.benchmarks.verify_paper_factor_values import oracle


def test_outer_window_changes_the_historical_signal():
    rng = np.random.default_rng(17)
    days = np.repeat(np.arange(280), 4)
    ordinal = np.arange(len(days))
    times = days.astype('int64') * 86_400_000_000_000 + (ordinal % 4) * 1_800_000_000_000
    price = 100 + np.cumsum(rng.normal(0, 0.1, len(days)))
    short, short_threshold = oracle(times, days, price, price, 10)
    long, long_threshold = oracle(times, days, price, price, 20)
    # Both versions have the same inner 250-day threshold. Their outer
    # quantile history differs at these three fully warmed-up observations.
    np.testing.assert_array_equal(short_threshold, long_threshold)
    np.testing.assert_array_equal(short[[1055, 1090, 1107]], [0, 0, 0])
    np.testing.assert_array_equal(long[[1055, 1090, 1107]], [1, -1, -1])


def test_threshold_comparison_cannot_hide_missing_suffix_values():
    from tests.benchmarks.verify_paper_factor_values import threshold_comparison
    result = threshold_comparison([1., 2., 3.], [1., np.nan, 3.])
    assert result['candidate_nonfinite'] == 1
    assert result['finite_status_mismatches'] == 1
    assert result['max_abs_error'] == 0


def test_threshold_comparison_requires_actual_comparable_observations():
    import pytest
    from tests.benchmarks.verify_paper_factor_values import threshold_comparison
    assert threshold_comparison([np.nan], [np.nan])['max_abs_error'] is None
    with pytest.raises(ValueError, match='equal nonempty'):
        threshold_comparison([], [])
    with pytest.raises(ValueError, match='equal nonempty'):
        threshold_comparison([1, 2], [1])
