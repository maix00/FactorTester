import numpy as np

from tools.data.DataMoneyMinorUnits import DataMoneyMinorUnits, minor_units_to_major, major_floor_to_minor_units, major_to_minor_units


def test_money_minor_units_rounds_only_after_amount_is_formed():
    per_unit_fixed_fee = 0.001

    assert int(major_to_minor_units(per_unit_fixed_fee)) == 0
    assert int(major_to_minor_units(10 * per_unit_fixed_fee)) == 1


def test_money_minor_units_vector_helpers_are_int_minor_units():
    values = np.array([1.234, 1.235, np.nan, np.inf])

    minor_units = major_to_minor_units(values)
    assert minor_units.dtype == np.int64
    np.testing.assert_array_equal(minor_units, np.array([123, 124, 0, 0], dtype=np.int64))

    floored = major_floor_to_minor_units(values)
    np.testing.assert_array_equal(floored, np.array([123, 123, 0, 0], dtype=np.int64))

    np.testing.assert_allclose(minor_units_to_major(minor_units), np.array([1.23, 1.24, 0.0, 0.0]))


def test_data_money_minor_units_scalar_object():
    money = DataMoneyMinorUnits.from_major(12.345)

    assert money.minor_units == 1235
    assert money.to_major() == 12.35
