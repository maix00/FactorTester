import pandas as pd
import pytest

from server.modules.single_factor_test.group import _apply_step_action, _step_should_pause


def test_step_control_continue_pauses_exactly_next_flow() -> None:
    control = {"mode": "end", "until": None}
    _apply_step_action(control, "continue")

    assert _step_should_pause(control, {"timestamp": "2026-01-02 09:00:00"})


def test_step_control_until_skips_flows_then_pauses_at_target() -> None:
    control = {"mode": "step", "until": None}
    _apply_step_action(control, "until", "2026-01-15 10:30:00")

    assert not _step_should_pause(control, {"timestamp": ""})
    assert not _step_should_pause(control, {"timestamp": "2026-01-15 10:29:59+08:00"})
    assert _step_should_pause(control, {"timestamp": "2026-01-15 10:30:00+08:00"})
    assert control == {"mode": "step", "until": None}


def test_step_control_end_never_pauses_but_does_not_cancel_computation() -> None:
    control = {"mode": "step", "until": pd.Timestamp("2026-01-01")}
    _apply_step_action(control, "end")

    assert not _step_should_pause(control, {"timestamp": "2026-01-31 15:00:00"})
    assert control["mode"] == "end"


@pytest.mark.parametrize("action, raw_until", [("until", "nope"), ("unknown", "")])
def test_step_control_rejects_invalid_commands(action: str, raw_until: str) -> None:
    with pytest.raises(ValueError):
        _apply_step_action({"mode": "step", "until": None}, action, raw_until)
