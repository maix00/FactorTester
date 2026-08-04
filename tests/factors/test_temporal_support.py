from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from Factors.MmRateOfChg import MmRateOfChg
from tools.data.types import DataFreq
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tester_calc.NextReturns import NextReturns
from tools.factors.temporal_support import (
    resolve_hac_lag,
    temporal_support_for_factor,
    temporal_support_for_ic,
)


def _next_returns(freq: str = "1d"):
    return NextReturns().get_factor(
        SC=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED.value,
        RF=freq,
        S=0,
        **{"$F": freq, "$Rev": "0"},
    )


def test_ic_contract_separates_factor_warmup_from_forward_label_support():
    factor = MmRateOfChg().get_factor(N="20d", **{"$F": "1d", "$Rev": "0"})
    support = temporal_support_for_ic(factor, returns_factor=_next_returns(), lag=0)

    assert support.factor_input_support_seconds == pd.Timedelta("20d").total_seconds()
    assert support.label_horizon_seconds == pd.Timedelta("1d").total_seconds()
    assert support.signal_interval_seconds == pd.Timedelta("1d").total_seconds()
    assert support.overlap_lag_signal_steps == 20
    assert support.support_status == "estimable"
    assert support.factor_input_source == "run_window.auto_warmup_window"


def test_hac_resolution_fails_closed_when_a_support_component_is_unknown():
    class RollingOp:
        _data_start = 1
        _n_data = 1

        def __init__(self):
            self._operands = (SimpleNamespace(value=object()), object())

        @property
        def window(self):
            return self._operands[0]

    factor = SimpleNamespace(freq=DataFreq.MIN1, _source_expr=RollingOp(), _source_freq=None)
    support = temporal_support_for_factor(
        factor,
        label_horizon_seconds=60.0,
        label_horizon_source="test:label",
        holding_support_seconds=0.0,
        holding_support_source="test:none",
        decay_support_seconds=0.0,
        decay_support_source="test:none",
    )

    resolution = resolve_hac_lag(support)

    assert support.support_status == "not_estimable"
    assert resolution.lag is None
    assert resolution.status == "not_estimable"
    assert resolution.source == "temporal_support"
    assert "factor_input_support" in (resolution.reason or "")


def test_explicit_hac_lag_is_not_an_alias_fallback():
    factor = MmRateOfChg().get_factor(N="1d", **{"$F": "1d", "$Rev": "0"})
    support = temporal_support_for_ic(factor, returns_factor=_next_returns(), lag=0)

    resolution = resolve_hac_lag(support, requested_lag=7, max_lag=4)

    assert resolution.lag == 4
    assert resolution.source == "explicit"
    assert resolution.status == "manual"


def test_integer_bar_windows_use_declared_source_frequency():
    class RollingOp:
        _data_start = 1
        _n_data = 1

        def __init__(self):
            self._operands = (SimpleNamespace(value=5), object())

        @property
        def window(self):
            return self._operands[0]

    factor = SimpleNamespace(
        freq=DataFreq.MIN1,
        _source_freq=DataFreq.MIN1,
        _source_expr=RollingOp(),
    )

    support = temporal_support_for_factor(
        factor,
        label_horizon_seconds=60.0,
        label_horizon_source="test:label",
        holding_support_seconds=0.0,
        holding_support_source="test:none",
        decay_support_seconds=0.0,
        decay_support_source="test:none",
    )

    assert support.factor_input_support_seconds == 5 * 60
    assert support.support_status == "estimable"
