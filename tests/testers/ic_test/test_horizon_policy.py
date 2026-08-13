from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import ICHorizonPolicy


def test_scale_aware_policy_resolves_per_factor_frequency() -> None:
    policy = ICHorizonPolicy.from_value({"sampling": "scale_aware"})

    one_minute = policy.resolve("1m")
    five_minutes = policy.resolve("5m")

    assert one_minute[0] == "MIN1"
    assert five_minutes[0] == "MIN5"
    assert "DAY1" in one_minute
    assert "DAY1" in five_minutes
    assert policy.to_dict() == {"mode": "scale_aware"}


def test_explicit_policy_deduplicates_physical_horizons() -> None:
    policy = ICHorizonPolicy.from_value({
        "sampling": "explicit",
        "bases": ["signal", "5m"],
        "multipliers": [1, 5],
    })

    assert policy.resolve("5m") == ("MIN5", "MIN25")


def test_explicit_policy_preserves_base_multiplier_order_for_primary_horizon() -> None:
    policy = ICHorizonPolicy.from_value({
        "sampling": "explicit",
        "bases": ["signal", "1m"],
        "multipliers": [1, 5],
    })

    assert policy.resolve("5m") == ("MIN5", "MIN25", "MIN1")


def test_signal_relative_policy_requires_a_factor_frequency() -> None:
    policy = ICHorizonPolicy.from_value({
        "sampling": "explicit", "bases": ["signal"], "multipliers": [1],
    })

    with pytest.raises(ValueError, match="signal frequency"):
        policy.resolve(None)
