from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.data.DataFreq import DataFreq
from tools.factors.tests.single_factor_test import ic as ic_module


def test_ic_evaluation_reuses_computed_factor_source_frequency(monkeypatch):
    evaluate_kwargs = {}

    class _ICFactor:
        table = pd.DataFrame({"IC": [0.25]})

        def clear(self):
            pass

        def evaluate(self, products, **kwargs):
            evaluate_kwargs.update(kwargs)

        def get_intermediate(self, name):
            return pd.DataFrame()

    class _ICFamily:
        def get_factor(self, **params):
            return _ICFactor()

    class _Tester:
        products = ["P"]
        start_date = None
        end_date = None

        def _get_result(self, factor):
            return SimpleNamespace(data_present_mask=pd.DataFrame())

    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    ic_module.run_ic_for_factor(
        _Tester(),
        {},
        [SimpleNamespace(_source_freq=DataFreq.MIN1)],
    )

    assert evaluate_kwargs == {"freq": DataFreq.MIN1}


def test_ic_evaluation_uses_declared_source_frequency_before_factor_is_computed(monkeypatch):
    evaluate_kwargs = {}

    class _ICFactor:
        table = pd.DataFrame({"IC": [0.25]})

        def clear(self):
            pass

        def evaluate(self, products, **kwargs):
            evaluate_kwargs.update(kwargs)

        def get_intermediate(self, name):
            return pd.DataFrame()

    class _ICFamily:
        def get_factor(self, **params):
            return _ICFactor()

    class _Tester:
        products = ["P"]
        start_date = None
        end_date = None

        def _get_result(self, factor):
            return SimpleNamespace(data_present_mask=pd.DataFrame())

    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    ic_module.run_ic_for_factor(
        _Tester(),
        {},
        [SimpleNamespace(_source_freq=None, family=SimpleNamespace(_source_freq="1m"))],
    )

    assert evaluate_kwargs == {"freq": DataFreq.MIN1}
