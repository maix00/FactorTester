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


def test_observed_sampling_does_not_treat_a_market_break_as_bars():
    from tests.benchmarks.verify_paper_factor_values import sample_signal
    minute = 60_000_000_000
    # A market break after 20 observations shifts the wall-clock grid while
    # the observed clock waits for the thirtieth actual Bar.
    times = np.r_[np.arange(20), np.arange(80, 100)].astype(np.int64) * minute
    values = np.arange(len(times), dtype=float)
    observed = sample_signal(times, values, 'observed_bars')
    assert np.isnan(observed[:29]).all()
    np.testing.assert_array_equal(observed[29:], np.full(11, 29.))
    wall = sample_signal(times, values, 'wall_clock')
    assert wall[20] == 19.
    assert np.isnan(observed[20])
    # No future observation can change a previously formed value.
    np.testing.assert_equal(observed[:35], sample_signal(times[:35], values[:35], 'observed_bars'))


def test_observed_clock_selection_matches_legacy_signal_align_with_a_gap():
    import pandas as pd
    from tools.factors.expr.signal_align import signal_align
    from tests.benchmarks.verify_paper_factor_values import sample_signal

    index = pd.DatetimeIndex(
        list(pd.date_range('2025-01-02 09:01', periods=20, freq='min'))
        + list(pd.date_range('2025-01-02 10:30', periods=50, freq='min')),
        name='MIN1',
    )
    values = np.arange(len(index), dtype=float)
    legacy = signal_align(pd.DataFrame({'T': values}, index=index), '30m', basepoint='last')
    np.testing.assert_array_equal(legacy['T'].to_numpy(), values[[29, 59]])
    sampled = sample_signal(index.as_unit('ns').asi8, values, 'observed_bars')
    np.testing.assert_array_equal(sampled[[29, 59]], legacy['T'].to_numpy())
