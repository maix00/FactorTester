from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.data.types import DataFreq
from tools.factors.tester_calc.single_factor_test import ic as ic_module
from tests.public_factor_source import load_public_factor_class


MmRateOfChg = load_public_factor_class("MmRateOfChg")


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
        start_dt = None
        end_dt = None

        def _get_result(self, factor):
            return SimpleNamespace(data_present_mask=pd.DataFrame())

    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    ic_module.run_ic_for_factor(
        _Tester(),
        {},
        [SimpleNamespace(_source_freq=DataFreq.MIN1)],
    )

    assert evaluate_kwargs == {"freq": DataFreq.MIN1, "start_dt": None, "end_dt": None}


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
        start_dt = None
        end_dt = None

        def _get_result(self, factor):
            return SimpleNamespace(data_present_mask=pd.DataFrame())

    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    ic_module.run_ic_for_factor(
        _Tester(),
        {},
        [SimpleNamespace(_source_freq=None, family=SimpleNamespace(_source_freq="1m"))],
    )

    assert evaluate_kwargs == {"freq": DataFreq.MIN1, "start_dt": None, "end_dt": None}


def test_ic_evaluation_passes_positive_factor_warmup_from_temporal_contract(monkeypatch):
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
        start_dt = None
        end_dt = None

        def _get_result(self, factor):
            return SimpleNamespace(data_present_mask=pd.DataFrame())

    factor = MmRateOfChg().get_factor(N="3d", **{"$F": "1d", "$Rev": "0"})
    monkeypatch.setattr(ic_module, "CrossSectionIC", _ICFamily)

    ic_module.run_ic_for_factor(
        _Tester(),
        {"RE": SimpleNamespace(freq=DataFreq.DAY1), "Lag": 0},
        [factor],
    )

    assert evaluate_kwargs["warmup_window"] == pd.Timedelta("3D")
