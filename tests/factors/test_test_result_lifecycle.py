from __future__ import annotations

import gc
from types import SimpleNamespace
import weakref

import numpy as np
import pandas as pd

from server.modules.single_factor_test.ic import _ICComputeResult, _build_ic_response
from tools.data.types.DataFreq import DataFreq
from tools.factors.FactorRunResult import FactorRunResult
from tools.factors.tests.single_factor_test import ic as ic_module


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

    _build_ic_response(
        tester,
        [new_factor],
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


def test_group_result_state_keeps_only_latest_run():
    result = FactorRunResult()
    first_returns = np.zeros((4, 2))
    first_returns_ref = weakref.ref(first_returns)
    first_group = SimpleNamespace(returns_np=first_returns)
    second_group = object()

    result.group_result = first_group
    del first_returns
    del first_group
    result.group_result = second_group
    gc.collect()

    assert result.group_result is second_group
    assert first_returns_ref() is None
