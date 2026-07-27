from __future__ import annotations

import pytest

from server.services.strategy_plans import normalize_strategy_plan


def test_strategy_plan_is_source_free_and_declares_kind() -> None:
    value = normalize_strategy_plan(
        [{
            "source": "profile:strategies/demo/actor.py",
            "strategy_id": "demo",
            "entrypoint": "Demo",
            "parameters": {"threshold": 2},
            "requirements": {"needs_timer_events": True},
        }],
        uploaded_paths=["strategies/demo/actor.py"],
    )[0]
    assert value["strategy_kind"] == "custom"
    assert value["parameters"] == {"threshold": 2}
    assert "source_code" not in value


def test_strategy_plan_rejects_unuploaded_or_invalid_custom_source() -> None:
    with pytest.raises(ValueError, match="not uploaded"):
        normalize_strategy_plan([{"source": "profile:strategies/demo.py"}])
    with pytest.raises(ValueError, match="strategies/<path>"):
        normalize_strategy_plan(
            [{"source": "profile:demo.py"}], uploaded_paths=["demo.py"],
        )


def test_strategy_plan_rejects_unknown_feed_event() -> None:
    with pytest.raises(ValueError, match="unknown strategy feed event"):
        normalize_strategy_plan([{
            "source": "builtin:group_quantile",
            "requirements": {"feed_events": ["l4"]},
        }])
