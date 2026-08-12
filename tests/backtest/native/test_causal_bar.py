from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.backtest.modules.causal_bar import CausalBar, visible_causal_bars


def test_causal_bar_uses_availability_cutoff_not_bar_end() -> None:
    bar = CausalBar(
        bar_end=pd.Timestamp("2024-01-01 09:05"),
        available_at=pd.Timestamp("2024-01-01 09:01"),
        values={"P1": 41.0},
    )

    assert not bar.is_visible_at(pd.Timestamp("2024-01-01 09:00"))
    assert bar.is_visible_at(pd.Timestamp("2024-01-01 09:01"))
    assert visible_causal_bars([bar], as_of=pd.Timestamp("2024-01-01 09:01")) == (bar,)


def test_causal_bar_does_not_leak_delayed_rows() -> None:
    bars = (
        CausalBar(
            bar_end=pd.Timestamp("2024-01-01 09:01"),
            available_at=pd.Timestamp("2024-01-01 09:01"),
            values={"P1": 41.0},
        ),
        CausalBar(
            bar_end=pd.Timestamp("2024-01-01 09:02"),
            available_at=pd.Timestamp("2024-01-01 09:03"),
            values={"P1": 42.0},
        ),
    )

    visible = visible_causal_bars(bars, as_of=pd.Timestamp("2024-01-01 09:02"))
    assert [bar.bar_end for bar in visible] == [pd.Timestamp("2024-01-01 09:01")]


def test_causal_bar_values_are_detached_from_caller() -> None:
    values = {"P1": 41.0}
    bar = CausalBar(
        bar_end=pd.Timestamp("2024-01-01 09:01"),
        available_at=pd.Timestamp("2024-01-01 09:01"),
        values=values,
    )
    values["P1"] = 99.0

    assert bar.values["P1"] == 41.0
    with pytest.raises(TypeError):
        bar.values["P1"] = 99.0  # type: ignore[index]

