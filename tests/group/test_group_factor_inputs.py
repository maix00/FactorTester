import pandas as pd
import numpy as np
import threading
from dataclasses import dataclass

from tools.data.types import DataFreq
from tools.factors.FactorRunResult import FactorRunResult
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tester_calc.single_factor_test.group import _FactorGroupTestGroup
from tools.factors.tester_calc.single_factor_test.group.core import ensure_group_factor_inputs
from tools.factors.tester_calc.single_factor_test.group.group_tester import FactorGroupTester
from tools.factors.FactorTester import FactorTester


class _FakeFactor:
    alias = "Fake"
    freq = DataFreq.MIN1
    _source_freq = None
    _expr = object()

    def __init__(self):
        self.evaluated = False

    def evaluate(self, products, freq=None):
        from tools.factors.FactorTester import _active_tester

        self.evaluated = True
        table = pd.DataFrame({"P": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2, freq="min"))
        _active_tester.get()._get_result(self).table = table
        self._source_freq = DataFreq.MIN1
        return table


class _FakeReturnsFactor:
    _expr = object()

    def __init__(self):
        self.cleared = False
        self.evaluated = False

    def evaluate(self, products, freq=None):
        self.evaluated = True
        return pd.DataFrame({"P": [0.01, 0.02]}, index=pd.date_range("2024-01-01", periods=2, freq="min"))

    def clear(self):
        self.cleared = True


class _FakeTester:
    def __init__(self):
        self.products = ["P"]
        self.results = {}
        self.discarded = []

    def _get_result(self, factor):
        self.results.setdefault(factor, FactorRunResult(factor=factor))
        return self.results[factor]

    def discard_result(self, factor, clear_factor=True):
        self.discarded.append(factor)


def test_group_inputs_compute_factor_table_without_prior_ic(monkeypatch):
    from tools.factors import eval_progress
    from tools.factors.tester_calc import NextReturns

    tester = _FakeTester()
    factor = _FakeFactor()
    returns_factor = _FakeReturnsFactor()
    tester._get_result(factor).returns = pd.DataFrame(
        {"P": [0.01, 0.02]},
        index=pd.date_range("2024-01-01", periods=2, freq="min"),
    )

    monkeypatch.setattr(eval_progress, "count_nodes", lambda expr: 1)
    monkeypatch.setattr(NextReturns, "get_factor", lambda self, **kwargs: returns_factor)

    ensure_group_factor_inputs(
        tester,
        factor,
        returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
    )

    result = tester._get_result(factor)
    assert factor.evaluated
    assert not result.table.empty
    assert not result.returns.empty
    assert not returns_factor.evaluated
    assert returns_factor not in tester.discarded


def test_group_inputs_compute_returns_without_prior_ic(monkeypatch):
    from tools.factors import eval_progress
    from tools.factors.tester_calc import NextReturns

    tester = _FakeTester()
    factor = _FakeFactor()
    returns_factor = _FakeReturnsFactor()
    tester._get_result(factor).table = pd.DataFrame(
        {"P": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="min"),
    )
    factor._source_freq = DataFreq.MIN1

    monkeypatch.setattr(eval_progress, "count_nodes", lambda expr: 1)
    monkeypatch.setattr(NextReturns, "get_factor", lambda self, **kwargs: returns_factor)

    ensure_group_factor_inputs(
        tester,
        factor,
        returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
    )

    result = tester._get_result(factor)
    assert not factor.evaluated
    assert returns_factor.evaluated
    assert not result.table.empty
    assert not result.returns.empty
    assert result.return_freq == DataFreq.MIN1
    assert returns_factor in tester.discarded


@dataclass
class _FakeSharedInputs:
    T: int
    signal_valid_cols: list
    index_list: list


class _FakeResolvedFactor:
    def __init__(self, alias):
        self.alias = alias


class _FakeRuntimeTester:
    alias = "tester-1"

    def resolve_factor(self, factor_alias):
        return _FakeResolvedFactor(factor_alias)


def test_factor_group_tester_keeps_multiple_factor_specs_in_one_simulation(monkeypatch):
    from tools.factors.tester_calc.single_factor_test.group import group_tester as group_tester_module

    fake_tester = _FakeRuntimeTester()
    groups = [
        _FactorGroupTestGroup(
            tester_id="tester-1",
            factor_alias="FactorA",
            n_groups=2,
            group_index=0,
            key="A-1",
            name="A-1",
        ),
        _FactorGroupTestGroup(
            tester_id="tester-1",
            factor_alias="FactorB",
            n_groups=2,
            group_index=1,
            key="B-2",
            name="B-2",
        ),
    ]
    prepared_aliases = []

    def fake_prepare(tester, factor, **kwargs):
        prepared_aliases.append(factor.alias)
        return _FakeSharedInputs(
            T=2,
            signal_valid_cols=["P"],
            index_list=list(pd.date_range("2024-01-01", periods=2, freq="min")),
        )

    def fake_memberships(factor, shared, *, group_counts):
        out = []
        for n_groups in group_counts:
            membership = np.zeros((shared.T, int(n_groups), len(shared.signal_valid_cols)), dtype=bool)
            membership[:, :, :] = True
            out.append(membership)
        return out

    monkeypatch.setattr(group_tester_module, "_prepare_group_shared_inputs", fake_prepare)
    monkeypatch.setattr(group_tester_module, "_build_group_memberships_from_shared", fake_memberships)

    tester = FactorGroupTester.from_flat_groups(
        groups,
        testers_by_id={"tester-1": fake_tester},
        spec_index_by_group={0: 0, 1: 0},
        calendar_index=None,
    )

    assert prepared_aliases == ["FactorA", "FactorB"]
    assert [spec.factor_alias for spec in tester.specs] == ["FactorA", "FactorB"]
    assert [spec.simulation_index for spec in tester.specs] == [0, 0]
    assert [spec.signal_membership_np.shape[1] for spec in tester.specs] == [1, 1]


def test_group_calendar_auto_preserves_factor_signal_events() -> None:
    tester = FactorTester.__new__(FactorTester)
    factor = _FakeFactor()
    factor.alias = "SparseSignal"
    factor.freq = DataFreq.MIN1
    factor._expr = object()
    tester.factors = [factor]
    tester.group_calendar_freq = "auto"
    tester.products = ["P"]
    tester._results_lock = threading.RLock()
    tester.results = {
        factor: FactorRunResult(factor=factor)
    }
    sparse_index = pd.to_datetime([
        "2024-01-01 09:00",
        "2024-01-01 09:07",
        "2024-01-01 09:30",
    ])
    tester.results[factor].table = pd.DataFrame({"P": [1.0, 2.0, 3.0]}, index=sparse_index)
    tester.results[factor].returns = pd.DataFrame({"P": [0.01, 0.02, 0.03]}, index=sparse_index)

    auto_index = tester.build_group_calendar_index(["SparseSignal"], requested_calendar_freq="auto")
    dense_index = tester.build_group_calendar_index(["SparseSignal"], requested_calendar_freq=DataFreq.MIN1)

    assert list(auto_index) == list(sparse_index)
    assert len(dense_index) == 31
    assert dense_index[0] == sparse_index[0]
    assert dense_index[-1] == sparse_index[-1]
