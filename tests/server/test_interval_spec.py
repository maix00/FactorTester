import pytest

from tools.factors.interval import IntervalSpec


def test_interval_is_inclusive_and_has_width():
    interval = IntervalSpec(10, 19)
    assert interval.width == 10
    assert interval.start == 10 and interval.end == 19


def test_interval_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        IntervalSpec(5, 4)
    with pytest.raises(ValueError):
        IntervalSpec(-1, 2)
