from __future__ import annotations

from pathlib import Path
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext

from server.services import transient_strategy_sources
from tools.factors.tester_calc.single_factor_test.group.research_run.strategy_loader import (
    strategy_objects_from_payload,
)


def test_profile_actor_source_loads_as_native_strategy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        transient_strategy_sources.Settings,
        "CACHE_DB_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    source = (
        "from tools.testers.backtest.engines.native.strategy import Strategy\n"
        "class Demo(Strategy):\n"
        "    def on_bar(self, ctx, bar):\n"
        "        return None\n"
    )
    scope = transient_strategy_sources.create_scope(
        owner="alice",
        entries=[{"path": "strategies/demo/actor.py", "source_code": source}],
    )
    objects = strategy_objects_from_payload({
        "_owner": "alice",
        "transient_strategy_source_scope_id": scope["scope_id"],
        "strategy_specs": [{
            "source": "profile:strategies/demo/actor.py",
            "entrypoint": "Demo",
            "strategy_id": "group-1",
            "parameters": {"threshold": 3},
            "data": {"price": "current_prices"},
        }],
    })
    assert objects["group-1"].alias == "group-1"
    assert objects["group-1"]._factortester_strategy_parameters["threshold"] == 3
    assert objects["group-1"]._factortester_strategy_data["price"] == "current_prices"
    transient_strategy_sources.cleanup_scope(scope["scope_id"])


def test_loaded_actor_parameters_reach_lifecycle_hook(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        transient_strategy_sources.Settings,
        "CACHE_DB_PATH",
        str(tmp_path / "cache.sqlite"),
    )
    source = (
        "from tools.testers.backtest.engines.native.strategy import Strategy\n"
        "class Demo(Strategy):\n"
        "    def on_start(self, ctx):\n"
        "        self.threshold = ctx.parameters['threshold']\n"
    )
    scope = transient_strategy_sources.create_scope(
        owner="alice",
        entries=[{"path": "strategies/demo/actor.py", "source_code": source}],
    )
    actor = strategy_objects_from_payload({
        "_owner": "alice",
        "transient_strategy_source_scope_id": scope["scope_id"],
        "strategy_specs": [{
            "source": "profile:strategies/demo/actor.py",
            "entrypoint": "Demo",
            "strategy_id": "group-1",
            "parameters": {"threshold": 7},
        }],
    })["group-1"]
    ctx = FlowContext(
        timestamp=None,
        event_queue=EventQueue(),
        active_strategies=frozenset({actor}),
        event_kind=None,
    )
    from tools.testers.backtest.modules.strategy_hooks import _call_start
    _call_start(object(), ctx)
    assert actor.threshold == 7
    transient_strategy_sources.cleanup_scope(scope["scope_id"])
