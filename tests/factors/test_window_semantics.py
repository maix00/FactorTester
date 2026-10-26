import pytest

from tools.factors.expr.window_semantics import (
    DEFAULT_MIN_PERIODS,
    DEFAULT_NAN_POLICY,
    NanPolicy,
    WindowSemantics,
)


def test_defaults_follow_upstream_full_window_nan_propagation():
    semantics = WindowSemantics(20)
    assert DEFAULT_MIN_PERIODS is None
    assert DEFAULT_NAN_POLICY is NanPolicy.PROPAGATE
    assert semantics.effective_min_periods == 20
    assert semantics.propagate_nan is True


def test_explicit_partial_window_and_skip_nan():
    semantics = WindowSemantics(20, min_periods=10, nan_policy=NanPolicy.SKIP)
    assert semantics.effective_min_periods == 10
    assert semantics.propagate_nan is False


def test_invalid_min_periods_rejected():
    with pytest.raises(ValueError):
        WindowSemantics(20, min_periods=0)
    with pytest.raises(ValueError):
        WindowSemantics(20, min_periods=21)
