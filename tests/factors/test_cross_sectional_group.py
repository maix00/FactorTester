from __future__ import annotations

import pandas as pd
import pytest

from tools.data.types import DataFreq, UniqueNameObject
from tools.factors.expr import EvaluateContext, FactorExpr
from tools.products.categories.Category import Category


class _Product(UniqueNameObject):
    pass


class _FrameExpr(FactorExpr):
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def _evaluate(self, ctx):
        return self.frame

    def _structural_key(self):
        return ("FrameExpr",)

    @property
    def op_name(self):
        return "frame"

    def _to_latex(self, subst=None):
        return "F_t"

    def _get_alias(self):
        return "FRAME"


def test_cs_group_rank_ranks_each_category_independently():
    copper = _Product(name="CU.SHF")
    aluminum = _Product(name="AL.SHF")
    soybean = _Product(name="M.DCE")
    palm = _Product(name="P.DCE")
    sector = Category.from_members(
        alias="GroupRankSector",
        type=_Product,
        labels={
            "metal": [copper, aluminum],
            "agri": [soybean, palm],
        },
    )
    values = pd.DataFrame({copper: [1.0], aluminum: [3.0], soybean: [100.0], palm: [200.0]})

    result = _FrameExpr(values).cs_group_rank(sector).evaluate(
        ctx=EvaluateContext(
            products=[copper, aluminum, soybean, palm],
            freq=DataFreq.MIN1,
            cache={},
        )
    )

    expected = pd.DataFrame({copper: [0.0], aluminum: [0.5], soybean: [0.0], palm: [0.5]})
    pd.testing.assert_frame_equal(result, expected)


def test_cs_group_zscore_and_demean_respect_category_membership_and_mask():
    left, right, excluded = (_Product(name=name) for name in ("A", "B", "C"))
    category = Category.from_members(
        alias="GroupNormalizeSector", type=_Product,
        labels={"included": [left, right], "other": [excluded]},
    )
    values = pd.DataFrame({left: [1.0], right: [3.0], excluded: [100.0]})
    mask = pd.DataFrame({left: [True], right: [True], excluded: [False]})

    zscore = _FrameExpr(values).cs_group_zscore(category, mask=_FrameExpr(mask)).evaluate(
        ctx=EvaluateContext(products=[left, right, excluded], freq=DataFreq.MIN1, cache={})
    )
    demean = _FrameExpr(values).cs_group_demean(category, mask=_FrameExpr(mask)).evaluate(
        ctx=EvaluateContext(products=[left, right, excluded], freq=DataFreq.MIN1, cache={})
    )

    assert zscore.iloc[0, 0] == pytest.approx(-0.7071067811865475)
    assert zscore.iloc[0, 1] == pytest.approx(0.7071067811865475)
    assert pd.isna(zscore.iloc[0, 2])
    assert demean.iloc[0, 0] == -1.0
    assert demean.iloc[0, 1] == 1.0
    assert pd.isna(demean.iloc[0, 2])


def test_cs_residualize_returns_cross_sectional_ols_residuals():
    products = [_Product(name=name) for name in ("A", "B", "C")]
    exposure = pd.DataFrame({products[0]: [1.0], products[1]: [2.0], products[2]: [3.0]})
    signal = pd.DataFrame({products[0]: [3.0], products[1]: [5.0], products[2]: [8.0]})

    result = _FrameExpr(signal).cs_residualize(_FrameExpr(exposure)).evaluate(
        ctx=EvaluateContext(products=products, freq=DataFreq.MIN1, cache={})
    )

    assert result.iloc[0, 0] == pytest.approx(1 / 6)
    assert result.iloc[0, 1] == pytest.approx(-1 / 3)
    assert result.iloc[0, 2] == pytest.approx(1 / 6)
