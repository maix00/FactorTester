from __future__ import annotations

import pandas as pd
import pytest

from tools.data.types import DataFreq, UniqueNameObject
from tools.factors.expr import CategoryBoolRef, EvaluateContext, build_panel_timeline
from tools.products.categories.Category import Category


class _Product(UniqueNameObject):
    pass


def _timeline(products: list[_Product]):
    frame = pd.DataFrame(
        {"CLOSE": [1.0, 2.0]},
        index=pd.to_datetime(["2025-01-02 09:00", "2025-01-02 09:01"]),
    )
    return build_panel_timeline(
        products,
        DataFreq.MIN1,
        {(product, "MIN1"): frame for product in products},
    )


def test_category_from_members_exposes_boolean_factor_expr_leaves():
    copper = _Product(name="CU.SHF")
    soybean = _Product(name="M.DCE")
    sector = Category.from_members(
        alias="ResearchSector",
        type=_Product,
        labels={"metal": ["CU.SHF"]},
    )

    result = sector["metal"].evaluate(
        ctx=EvaluateContext(
            products=[copper, soybean],
            freq=DataFreq.MIN1,
            cache={},
            panel_timeline=_timeline([copper, soybean]),
        )
    )

    expected = pd.DataFrame(
        {copper: [True, True], soybean: [False, False]},
        index=result.index,
        dtype=bool,
    )
    pd.testing.assert_frame_equal(result, expected)
    assert sector["Others"].evaluate(
        ctx=EvaluateContext(
            products=[copper, soybean],
            freq=DataFreq.MIN1,
            cache={},
            panel_timeline=_timeline([copper, soybean]),
        )
    ).iloc[0].to_dict() == {copper: False, soybean: True}


def test_category_from_members_rejects_overlaps_and_explicit_others():
    with pytest.raises(ValueError, match="both 'metal' and 'agri'"):
        Category.from_members(
            alias="OverlappingResearchSector",
            type=_Product,
            labels={"metal": ["CU.SHF"], "agri": ["CU.SHF"]},
        )
    with pytest.raises(ValueError, match="derived automatically"):
        Category.from_members(
            alias="ExplicitOthersResearchSector",
            type=_Product,
            labels={"Others": ["M.DCE"]},
        )


def test_category_label_selection_returns_category_boolean_factor_expr_leaf():
    sector = Category.from_members(
        alias="LeafResearchSector",
        type=_Product,
        labels={"metal": ["CU.SHF"]},
    )

    assert isinstance(sector["metal"], CategoryBoolRef)
    assert sector["metal"]._get_alias() == "CAT_LeafResearchSector_metal"
