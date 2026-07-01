from __future__ import annotations

import numpy as np
import pytest

from tools.data.types.data_money import DataMoney


def test_add_sub_major_units():
    a = DataMoney.from_major(100.0, currency="CNY", use_minor_units=False)
    b = DataMoney.from_major(30.0, currency="CNY", use_minor_units=False)
    assert (a + b).amount == pytest.approx(130.0)
    assert (a - b).amount == pytest.approx(70.0)


def test_add_sub_minor_units():
    a = DataMoney.from_major(100.0, currency="CNY", use_minor_units=True)
    b = DataMoney.from_major(30.0, currency="CNY", use_minor_units=True)
    assert (a + b).to_major() == pytest.approx(130.0)
    assert (a - b).to_major() == pytest.approx(70.0)


def test_mul_truediv():
    a = DataMoney.from_major(100.0, currency="CNY", use_minor_units=False)
    assert (a * 0.5).amount == pytest.approx(50.0)
    assert (a / 2).amount == pytest.approx(50.0)


def test_incompatible_raises():
    a = DataMoney.from_major(100.0, currency="CNY", use_minor_units=False)
    b = DataMoney.from_major(100.0, currency="USD", use_minor_units=False)
    with pytest.raises(ValueError):
        a + b
    c = DataMoney.from_major(100.0, currency="CNY", use_minor_units=True)
    with pytest.raises(ValueError):
        a + c


def test_vectorized_array_amount():
    a = DataMoney.from_major(np.array([100.0, 200.0]), currency="CNY", use_minor_units=False)
    b = DataMoney.from_major(np.array([10.0, 20.0]), currency="CNY", use_minor_units=False)
    np.testing.assert_array_almost_equal((a + b).amount, [110.0, 220.0])


def test_round_trip_major_minor():
    major = 123.45
    money = DataMoney.from_major(major, currency="CNY", use_minor_units=True)
    assert money.to_major() == pytest.approx(major, abs=0.01)
    money2 = DataMoney.from_major(major, currency="CNY", use_minor_units=False)
    assert money2.to_major() == pytest.approx(major)
