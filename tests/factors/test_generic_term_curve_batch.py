from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from tools.data.types import DataColumn, DataFreq
from tools.factors.expr import EvaluateContext, term_carry_annualized
from tools.products.AdjustableTermStructure import (
    AdjustableProductMixin,
    TERM_CONTRACT_UID_COL,
    TERM_DAYS_TO_MATURITY_COL,
    TERM_PRODUCT_COL,
    TERM_RANK_COL,
    TERM_TRADING_DAY_COL,
)


@dataclass
class _CountingStore:
    frame: pd.DataFrame
    loads: int = 0

    def load(self, product=None, trading_day=None, columns=None):
        self.loads += 1
        selected = self.frame
        if product is not None:
            selected = selected[selected[TERM_PRODUCT_COL] == product]
        if columns is not None:
            selected = selected.loc[:, columns]
        return selected.copy()


class _BatchProduct(AdjustableProductMixin):
    name = "BATCH"

    def __init__(self, store):
        self.store = store

    def get_term_structure_store(self, curve_variant="listed_contracts"):
        return self.store

    def get_some_data(self, _freq, copy=False):
        raise AssertionError("preloaded window must be authoritative")


def _term_frame(days):
    rows = []
    for offset, day in enumerate(days):
        near = 100.0 + offset
        rows.extend([
            {
                TERM_PRODUCT_COL: "BATCH",
                TERM_TRADING_DAY_COL: day,
                TERM_CONTRACT_UID_COL: f"N{offset}",
                TERM_RANK_COL: 0,
                TERM_DAYS_TO_MATURITY_COL: 10,
                DataColumn.CLOSE.name: near,
            },
            {
                TERM_PRODUCT_COL: "BATCH",
                TERM_TRADING_DAY_COL: day,
                TERM_CONTRACT_UID_COL: f"F{offset}",
                TERM_RANK_COL: 1,
                TERM_DAYS_TO_MATURITY_COL: 40,
                DataColumn.CLOSE.name: near * 0.95,
            },
        ])
    return pd.DataFrame(rows)


def test_generic_carry_loads_term_store_once_for_whole_window():
    days = pd.bdate_range("2025-01-02", periods=20)
    minute_index = pd.DatetimeIndex([
        day + pd.Timedelta(minutes=minute)
        for day in days
        for minute in range(3)
    ])
    store = _CountingStore(_term_frame(days))
    product = _BatchProduct(store)

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded={
            (product, DataFreq.MIN1.name): pd.DataFrame(
                {DataColumn.CLOSE.name: 1.0},
                index=minute_index,
            ),
        },
    ))

    expected = (1 / 0.95 - 1) * 365 / 30
    assert store.loads == 1
    assert result.index.equals(minute_index)
    assert result[product].tolist() == pytest.approx([expected] * len(minute_index))


def test_batch_curves_preserve_missing_day_as_nan():
    days = pd.to_datetime(["2025-01-02", "2025-01-03"])
    store = _CountingStore(_term_frame(days[:1]))
    product = _BatchProduct(store)
    index = days + pd.Timedelta(hours=9)

    result = term_carry_annualized().evaluate(ctx=EvaluateContext(
        products=[product],
        freq=DataFreq.MIN1,
        preloaded={
            (product, DataFreq.MIN1.name): pd.DataFrame(
                {DataColumn.CLOSE.name: 1.0},
                index=index,
            ),
        },
    ))

    assert result[product].notna().tolist() == [True, False]
