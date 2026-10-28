"""Python freezes configurations; the composed Rust runtime owns decisions."""
import pytest
from dataclasses import asdict
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup, ThresholdState


def test_group_configuration_is_frozen_without_python_decision_path():
    group = CrossSectionalGroup(5, 2)
    assert asdict(group) == {"split_count": 5, "group_index": 2}
    assert not hasattr(group, "members")
    with pytest.raises(ValueError): CrossSectionalGroup(5, 6)


def test_threshold_configuration_is_frozen_without_python_decision_path():
    state = ThresholdState(1, 0, "long_only")
    assert asdict(state) == {"entry": 1, "exit": 0, "side_mode": "long_only"}
    assert not hasattr(state, "direction")
    with pytest.raises(ValueError): ThresholdState(1, 2)
