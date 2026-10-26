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


def test_rolling_operator_carries_semantics_in_its_structural_key():
    from tools.data.types import DataColumn
    from tools.factors.expr.leaf import ColumnRef
    from tools.factors.expr.window_semantics import NanPolicy

    base = ColumnRef(DataColumn.CLOSE).rolling(20).mean()
    partial = (
        ColumnRef(DataColumn.CLOSE)
        .rolling(20)
        .semantics(min_periods=10, nan_policy=NanPolicy.SKIP)
        .mean()
    )
    assert base.min_periods is None
    assert base.nan_policy is NanPolicy.PROPAGATE
    assert partial.min_periods == 10
    assert partial.nan_policy is NanPolicy.SKIP
    assert base._structural_key() != partial._structural_key()


def test_groupby_scope_operator_carries_partition_semantics():
    from tools.data.types import DataColumn
    from tools.factors.expr.groupby_scope import GroupByScopeExpr
    from tools.factors.expr.leaf import ColumnRef
    from tools.factors.expr.lookback_scope import scope_bars

    base = GroupByScopeExpr(scope_bars(5), ColumnRef(DataColumn.CLOSE)).mean()
    partial = (
        GroupByScopeExpr(scope_bars(5), ColumnRef(DataColumn.CLOSE))
        .semantics(min_periods=3, nan_policy=NanPolicy.SKIP)
        .mean()
    )
    assert base.min_periods == 1
    assert base.nan_policy is NanPolicy.PROPAGATE
    assert partial.min_periods == 3
    assert partial.nan_policy is NanPolicy.SKIP
    assert base._structural_key() != partial._structural_key()
