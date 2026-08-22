from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

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


def test_ic_progress_reuses_execution_roots_for_node_count(monkeypatch):
    roots = []
    evaluated = []
    starts = []

    class _Expr:
        def _structural_key(self):
            return "root"

        def iter_children(self):
            return []

    class _Root:
        _expr = _Expr()

    class _Factor:
        _source_freq = DataFreq.MIN1
        _expr = _Expr()

    class _Tester:
        products = ["P"]
        start_dt = None
        end_dt = None

    class _Emitter:
        def emit_progress(self, *_args):
            pass

        def emit_start(self, **kwargs):
            starts.append(kwargs)

    def build(_params, _factor_list):
        root = _Root()
        roots.append(root)
        return root, DataFreq.MIN1

    monkeypatch.setattr(ic_module, "build_ic_factor", build)
    monkeypatch.setattr(
        ic_module,
        "collect_ic_result",
        lambda *_args: (
            [], pd.Series(dtype=float), pd.Series(dtype=float),
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(ic_module, "discard_ic_factor", lambda *_args: None)
    monkeypatch.setattr(
        "tools.factors.evaluation.evaluate_factors",
        lambda factors, **_kwargs: evaluated.extend(factors),
    )

    keys = [
        ("A", "MIN1", 0, "OPEN", "MIN1", 0, "rank", "F"),
        ("A", "MIN1", 0, "OPEN", "MIN5", 0, "rank", "F"),
    ]
    ic_module._compute_ic_groups(
        _Tester(), [(key, [_Factor()]) for key in keys],
        {key: {"FE": _Factor()} for key in keys},
        0, {"F": "MIN1"}, emitter=_Emitter(),
    )

    assert len(roots) == len(keys)
    assert evaluated == roots
    assert starts == [{"total": 4, "groups": 2, "phase": "init"}]


def test_ic_root_build_failure_discards_already_constructed_roots(monkeypatch):
    roots = []
    discarded = []

    class _Root:
        pass

    class _Factor:
        _source_freq = DataFreq.MIN1

    class _Tester:
        products = ["P"]
        start_dt = None
        end_dt = None

    def build(_params, _factor_list):
        if roots:
            raise RuntimeError("second root failed")
        root = _Root()
        roots.append(root)
        return root, DataFreq.MIN1

    monkeypatch.setattr(ic_module, "build_ic_factor", build)
    monkeypatch.setattr(
        ic_module,
        "discard_ic_factor",
        lambda _tester, root: discarded.append(root),
    )

    keys = [
        ("A", "MIN1", 0, "OPEN", "MIN1", 0, "rank", "F"),
        ("A", "MIN1", 0, "OPEN", "MIN5", 0, "rank", "F"),
    ]
    with pytest.raises(RuntimeError, match="second root failed"):
        ic_module._compute_ic_groups(
            _Tester(), [(key, [_Factor()]) for key in keys],  # type: ignore[arg-type]
            {key: {} for key in keys}, 0, {"F": "MIN1"},
        )

    assert discarded == roots


def test_ic_progress_reuses_legacy_root_without_source_frequency(monkeypatch):
    built = []
    evaluated = []
    discarded = []

    class _Expr:
        def _structural_key(self):
            return "legacy-root"

        def iter_children(self):
            return []

    class _Root:
        _expr = _Expr()

        def evaluate(self, products, **kwargs):
            evaluated.append((self, products, kwargs))

    class _Factor:
        _source_freq = None
        _expr = _Expr()

    class _Tester:
        products = ["P"]
        start_dt = None
        end_dt = None

    class _Emitter:
        def emit_progress(self, *_args):
            pass

        def emit_start(self, **_kwargs):
            pass

    def build(_params, _factor_list):
        root = _Root()
        built.append(root)
        return root, None

    monkeypatch.setattr(ic_module, "build_ic_factor", build)
    monkeypatch.setattr(ic_module, "_temporal_support_for_payload", lambda *_args: None)
    monkeypatch.setattr(
        ic_module,
        "collect_ic_result",
        lambda *_args, **_kwargs: (
            [], pd.Series(dtype=float), pd.Series(dtype=float),
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        ic_module,
        "discard_ic_factor",
        lambda _tester, root: discarded.append(root),
    )

    key = ("A", "", 0, "OPEN", "MIN1", 0, "rank", "F")
    ic_module._compute_ic_groups(
        _Tester(), [(key, [_Factor()])],  # type: ignore[arg-type]
        {key: {"FE": _Factor()}}, 0, {"F": "MIN1"}, emitter=_Emitter(),
    )

    assert len(built) == 1
    assert [item[0] for item in evaluated] == built
    assert discarded == built
