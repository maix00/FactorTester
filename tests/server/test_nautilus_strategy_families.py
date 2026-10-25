from __future__ import annotations

from server.services.nautilus_bridge.strategy_families import (
    CrossSectionalGroup,
    ThresholdState,
)


def test_cross_sectional_group_selects_nth_group_stably():
    values = {"T": 1.0, "TL": 2.0, "IC": 3.0, "IF": 4.0, "IH": 5.0}
    assert CrossSectionalGroup(5, 1).members(values) == ("T",)
    assert CrossSectionalGroup(5, 5).members(values) == ("IH",)
    assert CrossSectionalGroup(2, 1).members(values) == ("T", "TL")


def test_threshold_strategy_uses_factor_roles_not_orders():
    state = ThresholdState(entry=1.0, exit=0.0, side_mode="long_only")
    assert state.direction(1.2) == 1
    assert state.direction(-1.2) == 1
    assert state.direction(0.0) == 0
