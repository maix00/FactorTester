from __future__ import annotations

import gc
from types import SimpleNamespace
import weakref

import numpy as np
import pandas as pd

from server.modules.single_factor_test.ic import _ICComputeResult, _build_ic_response
from tools.data.types import DataFreq
from tools.factors.FactorRunResult import FactorRunResult
from tools.factors.tester_calc.single_factor_test import ic as ic_module


class _DisposableFactor:
    def __init__(self, alias: str = "Factor") -> None:
        self.alias = alias
        self.name = alias
        self.freq = None
        self.clear_count = 0

    def clear(self) -> None:
        self.clear_count += 1


def test_ic_scratch_factor_result_is_discarded_after_extraction(monkeypatch):
    scratch_factor = _DisposableFactor("CrossSectionIC")
    scratch_factor.table = pd.DataFrame({"IC": [0.25]})
    scratch_factor.evaluate = lambda products, **kwargs: None
    scratch_factor.get_intermediate = lambda name: pd.DataFrame({"P": [1.0]})

    class _ICFamily:
        def get_factor(self, **params):
            return scratch_factor

    class _Tester:
        products = ["P"]
        start_date = None
        end_date = None

        def __init__(self):
            self.results = {
                scratch_factor: SimpleNamespace(data_present_mask=pd.DataFrame({"P": [True]}))
            }
            self.discarded = []

        def _get_result(self, factor):
            return self.results[factor]

        def discard_result(self, factor):
            self.discarded.append(factor)
            self.results.pop(factor, None)
            factor.clear()

    tester = _Tester()
    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    output = ic_module.run_ic_for_factor(
        tester,
        {},
        [SimpleNamespace(_source_freq=DataFreq.MIN1)],
    )

    assert tester.discarded == [scratch_factor]
    assert tester.results == {}
    assert output[1].tolist() == [0.25]


def test_ic_response_replacement_discards_previous_alias_result():
    old_factor = _DisposableFactor("Signal|N:1m")
    new_factor = _DisposableFactor("Signal|N:1m")
    old_result = SimpleNamespace(
        ic_series=pd.Series([0.1]),
        ic_stats=pd.Series({"mean": 0.1}),
    )
    new_result = SimpleNamespace(
        ic_series=pd.Series([0.2]),
        ic_stats=pd.Series({"mean": 0.2}),
    )

    class _Tester:
        def __init__(self):
            self.factors = [old_factor]
            self.results = {old_factor: old_result, new_factor: new_result}
            self.discarded = []

        def discard_result(self, factor):
            self.discarded.append(factor)
            self.results.pop(factor, None)
            factor.clear()

    tester = _Tester()
    compute = _ICComputeResult()
    compute.factor_by_column[new_factor.alias] = new_factor
    compute.series_by_column_lag[new_factor.alias] = {0: pd.Series([0.2], dtype=float)}
    compute.stats_by_column_lag[new_factor.alias] = {0: pd.Series({"mean": 0.2}, dtype=float)}

    _build_ic_response(
        tester,
        [new_factor.alias],
        [],
        compute,
        "paths",
        [0],
        0,
        None,
        None,
    )

    assert tester.factors == [new_factor]
    assert tester.discarded == [old_factor]
    assert old_factor not in tester.results
    assert new_factor in tester.results
