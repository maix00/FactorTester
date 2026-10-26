from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from server.services.nautilus_bridge import strategy_backtest
from tools.factors.expr import CLOSE


def test_strategy_family_resolves_multiple_factor_roles(monkeypatch, tmp_path):
    class Resolver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def resolve(self, *, factor_ref="", alias=""):
            return SimpleNamespace(expr=CLOSE)

    monkeypatch.setattr(
        "server.modules.shared.run_spec_resolution.factors.RunFactorResolver",
        Resolver,
    )
    captured = {}
    monkeypatch.setattr(
        strategy_backtest, "run_strategy_family_replay",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )
    job_spec = {
        "_owner": "alice",
        "run_spec": {"configuration": {"shared": {"factors": [{"ref": "a"}]}}},
    }
    plan = {
        "strategy": {
            "kind": "cross_sectional_group",
            "parameters": {"split_count": 2, "group_index": 1},
            "factor_roles": {
                "signal": {"ref": "factor:v2:" + "a" * 43},
                "confirm": {"ref": "factor:v2:" + "b" * 43},
            },
        },
        "catalog_inputs": {
            "T": {"catalog_dir": str(tmp_path / "T"), "contract_uid": "CFFEX|F|T|2403"},
        },
        "max_input_bars": 8,
    }
    result = strategy_backtest.run_strategy_family_run_spec(
        job_spec=job_spec, plan=plan, output_dir=tmp_path / "out",
    )
    assert result == {"ok": True}
    assert sorted(captured["factor_bindings"]) == ["confirm", "signal"]
    assert captured["factor_refs"] == {"signal": "factor:v2:" + "a" * 43, "confirm": "factor:v2:" + "b" * 43}
    assert captured["family"].members({"T": 1.0}) == ()


def test_strategy_family_compiles_run_spec_execution_plan(monkeypatch, tmp_path):
    from tests.server.test_nautilus_bridge_config import _minimal_frozen

    class Resolver:
        def __init__(self, **kwargs): pass
        def resolve(self, *, factor_ref="", alias=""):
            return SimpleNamespace(expr=CLOSE)

    monkeypatch.setattr(
        "server.modules.shared.run_spec_resolution.factors.RunFactorResolver", Resolver,
    )
    captured = {}
    monkeypatch.setattr(
        strategy_backtest, "run_strategy_family_replay",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )
    settings = _minimal_frozen()
    job_spec = {
        "run_spec": {"configuration": {
            "shared": {"factors": [{"ref": "a"}]},
            "analyses": {"backtest": {"execution": {
                "nautilus_contract": {"settings": settings},
            }}},
        }},
    }
    plan = {
        "strategy": {
            "kind": "threshold", "parameters": {"entry_threshold": 1, "exit_threshold": 0},
            "factor_roles": {"signal": {"ref": "factor:v2:" + "a" * 43}},
        },
        "catalog_inputs": {"T": {"catalog_dir": str(tmp_path / "T"), "contract_uid": "CFFEX|F|T|2403"}},
        "max_input_bars": 8,
    }
    strategy_backtest.run_strategy_family_run_spec(job_spec=job_spec, plan=plan, output_dir=tmp_path)
    assert captured["execution_plan"] is not None


def test_strategy_family_engine_uses_frozen_venue(monkeypatch):
    from types import SimpleNamespace
    from server.services.nautilus_bridge import strategy_backtest

    plan = SimpleNamespace(
        venues=[{"name": "CFFEX"}, {"name": "SHFE"}],
        strategy_venue_bindings=[
            {"strategy_id": "s1", "venue_ids": ["CFFEX", "SHFE"]},
        ],
    )
    calls = {}
    monkeypatch.setattr(
        "server.services.nautilus_bridge.engine_factory.build_backtest_engine",
        lambda plan, instruments, trader_id: calls.update(
            plan=plan, instruments=instruments, trader_id=trader_id,
        ) or "engine",
    )
    engine, venue = strategy_backtest._build_strategy_family_engine(plan, ["i"])
    assert engine == "engine"
    assert str(venue) == "CFFEX"
    assert calls["instruments"] == {"s1": ["i"]}
