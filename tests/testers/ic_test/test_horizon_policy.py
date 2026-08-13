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


def test_resolved_horizon_keeps_multiplier_provenance_and_deduplicates_work() -> None:
    policy = ICHorizonPolicy.from_value({
        "sampling": "explicit",
        "bases": ["signal", "5m"],
        "multipliers": [1, 5],
    })

    resolved = policy.resolve_entries("5m")

    assert tuple(item.physical_frequency for item in resolved) == ("MIN5", "MIN25")
    assert resolved[0].to_dict() == {
        "physical_frequency": "MIN5",
        "origins": [
            {"base": "signal", "multiplier": 1},
            {"base": "MIN5", "multiplier": 1},
        ],
    }
    assert resolved[1].to_dict() == {
        "physical_frequency": "MIN25",
        "origins": [
            {"base": "signal", "multiplier": 5},
            {"base": "MIN5", "multiplier": 5},
        ],
    }


def test_signal_relative_policy_requires_a_factor_frequency() -> None:
    policy = ICHorizonPolicy.from_value({
        "sampling": "explicit", "bases": ["signal"], "multipliers": [1],
    })

    with pytest.raises(ValueError, match="signal frequency"):
        policy.resolve(None)
