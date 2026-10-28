"""The factor-series payload carries every nested layer of the factor.

A viewer that only shows the final signal hides how the chain contributed
(threshold, duration, fair price).  The serializer now exposes each
``as_intermediate`` series the runtime already computed.
"""

from __future__ import annotations

import pandas as pd

from server.modules.single_factor_test import evaluation


class _FakeFactor:
    def __init__(self, frames):
        from alpha.factor import ColumnRef, IntermediateIndex, IntermediateResults
        from types import SimpleNamespace
        nodes=tuple(ColumnRef(str(i)).as_intermediate(name) for i,name in enumerate(frames))
        index=IntermediateIndex(SimpleNamespace(operands=nodes))
        self._intermediate_results=IntermediateResults(index,'all')
        self._intermediate_results.replace({index.aliases[name]:value for name,value in frames.items()})


def test_intermediate_series_exposes_each_layer():
    frames = {"变动分位阈值": pd.DataFrame({"A": [1.0, 2.0]}), "当日差持续期": pd.DataFrame({"A": [3.0]})}
    out = list(evaluation._intermediate_series(_FakeFactor(frames)))
    assert [name for name, _ in out] == ["变动分位阈值", "当日差持续期"]
    assert all(isinstance(frame, pd.DataFrame) for _, frame in out)


def test_intermediate_series_skips_empty_and_broken_layers():
    frames = {"空": pd.DataFrame(), "坏": RuntimeError("boom"), "好": pd.DataFrame({"A": [1.0]})}
    out = list(evaluation._intermediate_series(_FakeFactor(frames)))
    assert [name for name, _ in out] == ["好"]


def test_intermediate_series_is_bounded():
    frames = {f"层{i}": pd.DataFrame({"A": [1.0]}) for i in range(20)}
    out = list(evaluation._intermediate_series(_FakeFactor(frames), limit=3))
    assert len(out) == 3


def test_serializer_marks_nested_items():
    source = (evaluation.__file__)
    text = open(source, encoding="utf-8").read()
    assert '"nested_of"' in text
    assert "_intermediate_series(factor, result=result)" in text
