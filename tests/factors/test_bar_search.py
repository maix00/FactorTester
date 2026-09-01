from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import tools.factors as public_factors
import tools.factors.expr as public_expr
from tools.data.types import DataFreq
from tools.factors import (
    CANDIDATE as PUBLIC_CANDIDATE,
)
from tools.factors import (
    CURRENT as PUBLIC_CURRENT,
)
from tools.factors import (
    FactorFamily,
)
from tools.factors import (
    scope_bars as public_scope_bars,
)
from tools.factors.expr import (
    CANDIDATE,
    CURRENT,
    EvaluateContext,
    bar_since,
    scope_bars,
    scope_session,
    scope_trading_day,
)
from tools.factors.expr.core import FactorExpr
from tools.factors.expr.timeline import PanelTimeline
from tools.factors.FactorExpr import CLOSE_RAW, VOLUME
from tools.parameters import FactorParam, WindowParam


class _FrameExpr(FactorExpr):
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        return self.frame

    def _structural_key(self) -> tuple:
        return ("frame", id(self))

    def _to_latex(self, subst=None) -> str:
        return "X"

    def _get_alias(self) -> str:
        return "X"


def _ctx(products=("A",)) -> EvaluateContext:
    return EvaluateContext(products=products, freq=DataFreq.MIN1, cache={})


def _timeline_ctx(index: pd.Index, products=("A",)) -> EvaluateContext:
    timeline = PanelTimeline(
        index=index,
        products=products,
        trading_days=pd.Index(pd.DatetimeIndex(index).normalize(), name="DAY1"),
        observed_mask=pd.DataFrame(True, index=index, columns=products),
        same_session=True,
    )
    return EvaluateContext(
        products=products,
        freq=DataFreq.MIN1,
        cache={},
        panel_timeline=timeline,
    )


def test_bar_since_defaults_to_nearest_match_in_fixed_bar_scope():
    index = pd.date_range("2026-01-01 09:01", periods=7, freq="min")
    condition = _FrameExpr(pd.DataFrame(
        {"A": [False, True, False, False, True, False, False]},
        index=index,
    ))

    result = bar_since(condition, scope=scope_bars(4), default=4).evaluate(ctx=_ctx())

    np.testing.assert_allclose(result["A"], [4, 0, 1, 2, 0, 1, 2])


def test_bar_since_can_select_farthest_match_in_fixed_bar_scope():
    index = pd.date_range("2026-01-01 09:01", periods=7, freq="min")
    condition = _FrameExpr(pd.DataFrame(
        {"A": [False, True, False, True, True, False, False]},
        index=index,
    ))

    result = bar_since(
        condition,
        scope=scope_bars(4),
        select="farthest",
        default=4,
    ).evaluate(ctx=_ctx())

    np.testing.assert_allclose(result["A"], [4, 0, 1, 2, 3, 4, 3])


def test_bar_since_omitted_default_tracks_scope_and_explicit_nan_remains_missing():
    index = pd.date_range("2026-01-01 09:01", periods=4, freq="min")
    condition = _FrameExpr(pd.DataFrame({"A": [False] * 4}, index=index))

    dynamic = bar_since(condition, scope=scope_bars(2)).evaluate(ctx=_ctx())
    missing = bar_since(condition, scope=scope_bars(2), default=np.nan).evaluate(ctx=_ctx())

    np.testing.assert_allclose(dynamic["A"], [0, 1, 2, 2])
    assert missing["A"].isna().all()


def test_bar_since_can_exclude_current_bar_without_losing_distance():
    index = pd.date_range("2026-01-01 09:01", periods=4, freq="min")
    condition = _FrameExpr(pd.DataFrame(
        {"A": [True, False, True, False]}, index=index,
    ))

    result = bar_since(
        condition,
        scope=scope_bars(2),
        default=8,
        include_current=False,
    ).evaluate(ctx=_ctx())

    np.testing.assert_allclose(result["A"], [8, 1, 2, 1])


def test_bar_distance_matches_nearest_dynamic_historical_candidate():
    index = pd.date_range("2026-01-01 09:01", periods=6, freq="min")
    value = _FrameExpr(pd.DataFrame(
        {"A": [100.0, 100.05, 100.2, 100.21, 100.5, 100.51]},
        index=index,
    ))
    condition = (CURRENT - CANDIDATE).abs() / CURRENT.abs() >= 0.001

    result = value.bar_distance(
        condition,
        scope=scope_bars(3),
        default=3,
    ).evaluate(ctx=_ctx())

    np.testing.assert_allclose(result["A"], [3, 3, 1, 2, 1, 2])


def test_bar_distance_default_tracks_available_scope_length():
    index = pd.to_datetime([
        "2026-01-01 09:01", "2026-01-01 09:02", "2026-01-01 09:03",
        "2026-01-01 21:01", "2026-01-01 21:02",
    ])
    values = _FrameExpr(pd.DataFrame({"A": [1.0] * 5}, index=index))

    result = values.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_session(),
    ).evaluate(ctx=_timeline_ctx(index))

    np.testing.assert_allclose(result["A"], [0, 1, 2, 0, 1])


def test_bars_accepts_a_duration_window_without_window_bars_wrapper():
    index = pd.date_range("2026-01-01 09:01", periods=5, freq="min")
    value = _FrameExpr(pd.DataFrame({"A": [1.0, 1.0, 2.0, 2.0, 3.0]}, index=index))
    maximum = WindowParam("K", default_value="3m")
    expr = value.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_bars(maximum),
        default=9,
    ).resolve(param_values={"K": pd.Timedelta("3m")})

    result = expr.evaluate(ctx=EvaluateContext(
        products=("A",), freq=DataFreq.MIN1, cache={},
    ))

    np.testing.assert_allclose(result["A"], [9, 9, 1, 2, 1])


def test_bar_distance_can_select_farthest_dynamic_historical_candidate():
    index = pd.date_range("2026-01-01 09:01", periods=5, freq="min")
    value = _FrameExpr(pd.DataFrame(
        {"A": [10.0, 11.0, 12.0, 13.0, 14.0]},
        index=index,
    ))

    result = value.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_bars(3),
        select="farthest",
        default=3,
    ).evaluate(ctx=_ctx())

    np.testing.assert_allclose(result["A"], [3, 1, 2, 3, 3])


def test_bar_since_session_scope_resets_after_session_gap():
    index = pd.to_datetime([
        "2026-01-01 09:01", "2026-01-01 09:02", "2026-01-01 09:03",
        "2026-01-01 21:01", "2026-01-01 21:02",
    ])
    condition = _FrameExpr(pd.DataFrame(
        {"A": [True, False, False, False, True]},
        index=index,
    ))

    result = bar_since(
        condition,
        scope=scope_session(),
        default=9,
    ).evaluate(ctx=_timeline_ctx(index))

    np.testing.assert_allclose(result["A"], [0, 1, 2, 9, 0])


def test_bar_since_session_scope_uses_finest_multiindex_time_level():
    timestamps = pd.to_datetime([
        "2026-01-01 09:01", "2026-01-01 09:02", "2026-01-01 21:01",
    ])
    index = pd.MultiIndex.from_arrays(
        [timestamps.normalize(), timestamps], names=["DAY1", "MIN1"],
    )
    condition = _FrameExpr(pd.DataFrame({"A": [True, False, False]}, index=index))
    timeline = PanelTimeline(
        index=index,
        products=("A",),
        trading_days=pd.Index(timestamps.normalize(), name="DAY1"),
        observed_mask=pd.DataFrame(True, index=index, columns=["A"]),
        same_session=True,
    )

    result = bar_since(condition, scope=scope_session(), default=7).evaluate(
        ctx=EvaluateContext(
            products=("A",), freq=DataFreq.MIN1, cache={}, panel_timeline=timeline,
        ),
    )

    np.testing.assert_allclose(result["A"], [0, 1, 7])


def test_bar_since_counts_each_products_observed_bars_on_async_panel():
    index = pd.date_range("2026-01-01 09:01", periods=5, freq="min")
    condition = _FrameExpr(pd.DataFrame(
        {"A": [True, False, False, False, False]}, index=index,
    ))
    observed = pd.DataFrame(
        {"A": [True, False, True, False, True]}, index=index,
    )
    timeline = PanelTimeline(
        index=index,
        products=("A",),
        trading_days=pd.Index(index.normalize(), name="DAY1"),
        observed_mask=observed,
        same_session=True,
    )

    result = bar_since(condition, scope=scope_bars(2), default=6).evaluate(
        ctx=EvaluateContext(
            products=("A",), freq=DataFreq.MIN1, cache={}, panel_timeline=timeline,
        ),
    )

    np.testing.assert_allclose(result["A"], [0, np.nan, 1, np.nan, 2], equal_nan=True)


def test_bar_distance_trading_day_scope_cannot_match_previous_day():
    index = pd.to_datetime([
        "2026-01-01 14:59", "2026-01-01 15:00",
        "2026-01-02 09:01", "2026-01-02 09:02",
    ])
    value = _FrameExpr(pd.DataFrame({"A": [1.0, 2.0, 10.0, 11.0]}, index=index))

    result = value.bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_trading_day(),
        default=8,
    ).evaluate(ctx=_timeline_ctx(index))

    np.testing.assert_allclose(result["A"], [8, 1, 8, 1])


class _DurationFamily(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        threshold = FactorParam("Th", default_value=0.001)
        maximum = FactorParam("K", default_value=3)
        condition = (
            (CURRENT - CANDIDATE).abs()
            / (CURRENT.abs() + 1e-10)
            >= threshold
        )
        price_duration = CLOSE_RAW.bar_distance(
            condition, scope=scope_bars(maximum), default=maximum,
        )
        volume_duration = VOLUME.bar_distance(
            condition, scope=scope_bars(maximum), default=maximum,
        )
        return (price_duration + volume_duration) / 2.0


def test_lookback_scope_public_api_has_only_explicit_scope_names():
    for module in (public_factors, public_expr):
        assert hasattr(module, "scope_bars")
        assert hasattr(module, "scope_session")
        assert hasattr(module, "scope_trading_day")
        assert not hasattr(module, "bars")
        assert not hasattr(module, "session")
        assert not hasattr(module, "trading_day")


def test_factor_family_can_resolve_and_evaluate_duration_bar_search_params():
    assert PUBLIC_CURRENT is CURRENT
    assert PUBLIC_CANDIDATE is CANDIDATE
    assert public_scope_bars(3).resolved_count() == 3
    family = _DurationFamily()
    factor = family.factor_from_alias(family.get_alias(Th=0.001, K=3, **{"$F": "1m"}))
    index = pd.date_range("2026-01-01 09:01", periods=4, freq="min")
    preloaded = {
        ("A", DataFreq.MIN1.name): pd.DataFrame(
            {
                "CLOSE": [100.0, 100.05, 100.2, 100.21],
                "VOLUME": [1000.0, 1000.5, 1002.0, 1002.1],
            },
            index=index,
        ),
    }

    result = factor._source_expr.evaluate(ctx=EvaluateContext(
        products=("A",),
        freq=DataFreq.MIN1,
        cache={},
        preloaded=preloaded,
    ))

    np.testing.assert_allclose(result["A"], [3.0, 3.0, 1.0, 2.0])


def test_bar_search_identity_and_latex_include_scope_and_selection():
    value = _FrameExpr(pd.DataFrame({"A": [1.0]}))
    nearest = value.bar_distance(
        CANDIDATE < CURRENT, scope=scope_bars(3), default=3,
    )
    farthest = value.bar_distance(
        CANDIDATE < CURRENT, scope=scope_bars(3), select="farthest", default=3,
    )

    assert nearest.semantic_fingerprint() != farthest.semantic_fingerprint()
    assert "BarDistance" in nearest.to_latex()
    assert "nearest" in nearest.to_latex()


def test_bar_search_latex_formats_selection_parentheses_and_resolved_scope():
    maximum = FactorParam("K", default_value=3)
    expr = _FrameExpr(pd.DataFrame({"A": [1.0]})).bar_distance(
        CANDIDATE < CURRENT,
        scope=scope_bars(maximum),
    ).resolve(param_values={"K": 3})

    latex = expr.to_latex()

    assert r"^{\mathrm{nearest}}" in latex
    assert r"_{\mathrm{bars}\left(3\right)}" in latex
    assert r"\left(" in latex
    assert r"\right)" in latex


def test_match_placeholders_cannot_escape_bar_distance_condition():
    with pytest.raises(ValueError, match="only valid inside"):
        CURRENT.evaluate(ctx=_ctx())
