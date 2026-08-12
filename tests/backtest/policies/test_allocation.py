from __future__ import annotations

import pytest

from tools.testers.backtest.policies.allocation import equal_weight, inverse_measure_weight


def test_equal_weight_normalizes_selected_items():
    assert equal_weight({"A", "B"}) == {"A": 0.5, "B": 0.5}
    assert equal_weight(set()) == {}


def test_inverse_measure_weight_assigns_more_to_lower_measure():
    weights = inverse_measure_weight({"A", "B"}, {"A": 1.0, "B": 2.0})

    assert weights == pytest.approx({"A": 2 / 3, "B": 1 / 3})


def test_inverse_measure_weight_reserves_equal_share_for_missing_measure():
    weights = inverse_measure_weight({"A", "B", "C"}, {"A": 1.0, "B": 2.0})

    assert weights == pytest.approx({"A": 4 / 9, "B": 2 / 9, "C": 1 / 3})


def test_inverse_measure_weight_can_exclude_missing_items():
    weights = inverse_measure_weight(
        {"A", "B", "C"},
        {"A": 1.0, "B": 2.0},
        missing="exclude",
    )

    assert weights == pytest.approx({"A": 2 / 3, "B": 1 / 3})


def test_inverse_measure_weight_falls_back_to_equal_when_no_measure_is_valid():
    assert inverse_measure_weight({"A", "B"}, {}, missing="exclude") == {"A": 0.5, "B": 0.5}
