from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.data.types import DataFreq
from server.modules.single_factor_test import ic as ic_module


def test_ic_groups_batch_roots_with_the_same_source_frequency(monkeypatch):
    roots = []
    discarded = []
    evaluated = []

    class _Root:
        pass

    class _Factor:
        _source_freq = DataFreq.MIN1

    class _Tester:
        products = ["P"]
        start_dt = None
        end_dt = None

    def build(_params, _factor_list):
        root = _Root()
        roots.append(root)
        return root, DataFreq.MIN1

    def evaluate(factors, **kwargs):
        evaluated.append((list(factors), kwargs))

    def collect(_tester, _root, _factor_list):
        return (
            [], pd.Series(dtype=float), pd.Series(dtype=float),
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        )

    monkeypatch.setattr(ic_module, "build_ic_factor", build)
    monkeypatch.setattr(ic_module, "collect_ic_result", collect)
    monkeypatch.setattr(ic_module, "discard_ic_factor", lambda _tester, root: discarded.append(root))
    monkeypatch.setattr("tools.factors.evaluation.evaluate_factors", evaluate)

    keys = [
        ("A", "MIN1", 0, "OPEN", "MIN1", 0, "rank", "F"),
        ("A", "MIN1", 0, "OPEN", "MIN5", 0, "rank", "F"),
    ]
    result = ic_module._compute_ic_groups(
        _Tester(), [(key, [_Factor()]) for key in keys],
        {key: {} for key in keys}, 0, {"F": "MIN1"},
    )

    assert result.series_by_column_horizon_lag == {}
    assert len(evaluated) == 1
    assert evaluated[0][0] == roots
    assert evaluated[0][1]["freq"] == DataFreq.MIN1
    assert discarded == roots
