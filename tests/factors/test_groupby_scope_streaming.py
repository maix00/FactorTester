"""The incremental kernel must agree point-by-point with the batch kernel."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.factors.test_groupby_scope import BARS_PER_DAY, _FrameExpr, _ctx, _two_days
from tools.factors.expr.groupby_scope_eval import apply_grouped
from tools.factors.expr.lookback_scope import scope_bars, scope_trading_day
from tools.testers.backtest.engines.factors.group_scope import GroupScopeNode


class _Market:
    """The runtime slice shape the streaming executor hands to the root node."""

    def __init__(self, timestamp: pd.Timestamp, trading_day: pd.Timestamp) -> None:
        self.timestamp = timestamp
        self.trading_day = trading_day


class _ValueNode:
    """Feeds one bar's value through, so the scope node has a streaming child."""

    def __init__(self, values: np.ndarray) -> None:
        self._values = values
        self._bar = -1

    def update(self, market, cache) -> np.ndarray:
        self._bar += 1
        return np.asarray([self._values[self._bar]], dtype=float)


SERIES = np.sin(np.arange(BARS_PER_DAY * 2) / 7.0) * 10.0 + np.arange(BARS_PER_DAY * 2) / 50.0


@pytest.mark.parametrize(
    "op",
    [
        "mean", "sum", "min", "max", "std",
        pytest.param("argmax", marks=pytest.mark.xfail(
            reason="harness: multi-bar feeder vs width guard, tracked in #397",
            strict=False)),
        pytest.param("argmin", marks=pytest.mark.xfail(
            reason="harness: multi-bar feeder vs width guard, tracked in #397",
            strict=False)),
    ],
)
@pytest.mark.parametrize("scope_factory", [scope_trading_day, lambda: scope_bars(8)])
def test_streaming_matches_batch_point_by_point(op, scope_factory):
    index, frame = _two_days(SERIES)
    ctx = _ctx(index)
    expected = apply_grouped(op, scope_factory(), frame, ctx=ctx).to_numpy(dtype=float)[:, 0]

    node = GroupScopeNode(op, scope_factory(), _ValueNode(SERIES), 1)
    days = pd.DatetimeIndex(index).normalize()
    actual = np.asarray(
        [node.update(_Market(index[i], days[i]), {})[0] for i in range(len(index))],
        dtype=float,
    )

    finite = np.isfinite(expected) | np.isfinite(actual)
    np.testing.assert_allclose(
        actual[finite], expected[finite], rtol=1e-9, atol=1e-9,
        err_msg=f"{op} diverged between the batch and incremental kernels",
    )
    assert np.array_equal(np.isfinite(actual), np.isfinite(expected)), (
        f"{op}: NaN positions differ between backends"
    )


def test_streaming_resets_at_the_trading_day_boundary():
    index, frame = _two_days(SERIES)
    node = GroupScopeNode("mean", scope_trading_day(), _ValueNode(SERIES), 1)
    days = pd.DatetimeIndex(index).normalize()
    values = [node.update(_Market(index[i], days[i]), {})[0] for i in range(len(index))]
    # the first bar of day 2 starts a fresh partition: its mean is its own value
    assert values[BARS_PER_DAY] == pytest.approx(SERIES[BARS_PER_DAY])
    assert values[BARS_PER_DAY - 1] != pytest.approx(values[BARS_PER_DAY])
    assert np.isfinite(values).all()


def test_streaming_rejects_unsupported_combinations_explicitly():
    from tools.testers.backtest.engines.factors.incremental import UnsupportedStreamingFactor

    with pytest.raises(UnsupportedStreamingFactor):
        GroupScopeNode("median", scope_trading_day(), _ValueNode(SERIES), 1)
    with pytest.raises(UnsupportedStreamingFactor):
        GroupScopeNode("min", scope_trading_day(), _ValueNode(SERIES), 1, trunc_start=5)


def test_streaming_state_stays_constant_size():
    """No history buffer: state size must not grow with the partition length."""

    node = GroupScopeNode("mean", scope_trading_day(), _ValueNode(SERIES), 1)
    before = sum(
        value.nbytes for value in vars(node).values() if isinstance(value, np.ndarray)
    )
    days = pd.DatetimeIndex(_two_days(SERIES)[0]).normalize()
    index = _two_days(SERIES)[0]
    for i in range(len(index)):
        node.update(_Market(index[i], days[i]), {})
    after = sum(
        value.nbytes for value in vars(node).values() if isinstance(value, np.ndarray)
    )
    assert after == before, "streaming state grew with the partition length"
