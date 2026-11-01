from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services.nautilus_bridge import strategy_backtest
from tools.factors.expr import CLOSE


def test_frozen_catalog_frequency_drives_time_window_compilation():
    def opened(*bar_types):
        return {str(i): (None, None, {"bar_type": bar_type}, None)
                for i, bar_type in enumerate(bar_types)}

    minute = "T2403.CFFEX-1-MINUTE-LAST-EXTERNAL"
    thirty_minutes = "T2403.CFFEX-30-MINUTE-LAST-EXTERNAL"
    frequency = strategy_backtest._source_frequency(opened(thirty_minutes))
    spec, _ = strategy_backtest._compile_frozen_roots(
        {"factor": CLOSE.rolling("1h").mean()}, ("T",), None,
        source_freq=frequency,
    )
    assert next(node for node in spec["nodes"] if node["kind"] == "rolling")["window"] == 2
    daily = strategy_backtest._source_frequency(opened("T2403.CFFEX-1-DAY-LAST-EXTERNAL"))
    assert daily == strategy_backtest.DataFreq.DAY1
    with pytest.raises(ValueError, match="single positive Bar frequency"):
        strategy_backtest._source_frequency(opened(minute, thirty_minutes))
    with pytest.raises(ValueError, match="time-aggregated"):
        strategy_backtest._source_frequency(opened("T2403.CFFEX-1-TICK-LAST-EXTERNAL"))


def test_strategy_replay_uses_frozen_catalog_frequency_before_compilation(monkeypatch, tmp_path):
    from nautilus_trader import _libnautilus
    from server.services.nautilus_bridge.strategy_families import ThresholdState

    monkeypatch.setattr(_libnautilus, "attach_factor_family", lambda **kwargs: None, raising=False)
    monkeypatch.setattr(strategy_backtest, "_load_input", lambda _: (
        None, None, {"bar_type": "T2403.CFFEX-30-MINUTE-LAST-EXTERNAL"}, None,
    ))
    monkeypatch.setattr(strategy_backtest, "preflight_catalogs", lambda *args, **kwargs: None)
    class StopAfterCompilation(Exception): pass
    original = strategy_backtest._compile_frozen_roots
    def check_compile(expressions, products, calendar, *, source_freq):
        spec, _ = original(expressions, products, calendar, source_freq=source_freq)
        assert next(node for node in spec["nodes"] if node["kind"] == "rolling")["window"] == 2
        raise StopAfterCompilation
    monkeypatch.setattr(strategy_backtest, "_compile_frozen_roots", check_compile)
    with pytest.raises(StopAfterCompilation):
        strategy_backtest.run_strategy_families_replay(
            inputs={"T": object()}, output_dir=tmp_path,
            strategies=[{"strategy_id": "s", "factor_bindings": {"signal": CLOSE.rolling("1h").mean()},
                         "factor_refs": {"signal": "factor:v2:" + "a" * 43},
                         "family": ThresholdState(1, 0)}],
        )


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
    assert captured["family"].split_count == 2
    assert captured["family"].group_index == 1


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


@pytest.mark.parametrize(("warmup", "expected_start"), [
    ({"mode": "custom", "data_start_utc": "2024-01-02T01:30:00Z"}, "2024-01-02T01:30:00+00:00"),
    ({"mode": "disabled", "diagnostic_only": True}, "2025-04-01T01:00:00Z"),
    ({"mode": "custom", "data_start_utc": "2025-04-02T01:00:00Z"}, None),
])
def test_frozen_warmup_controls_staging_window(monkeypatch, tmp_path, warmup, expected_start):
    from tests.server.test_nautilus_bridge_config import _minimal_frozen

    class Resolver:
        def __init__(self, **kwargs): pass
        def resolve(self, **kwargs): return SimpleNamespace(expr=CLOSE)

    monkeypatch.setattr(
        "server.modules.shared.run_spec_resolution.factors.RunFactorResolver", Resolver,
    )
    calls = {}
    monkeypatch.setattr(
        "server.services.nautilus_bridge.catalog_staging.stage_run_spec_catalogs",
        lambda **kwargs: calls.update(kwargs) or {
            "T": {"catalog_dir": str(tmp_path), "contract_uid": "CFFEX|F|T|2403"}
        },
    )
    monkeypatch.setattr(strategy_backtest, "run_strategy_family_replay", lambda **kwargs: kwargs)
    settings = _minimal_frozen(factor_warmup=warmup)
    job_spec = {"run_spec": {"configuration": {
        "shared": {"factors": []},
        "analyses": {"backtest": {"execution": {"nautilus_contract": {"settings": settings}}}},
    }}}
    plan = {
        "strategy": {"kind": "threshold", "parameters": {},
                     "factor_roles": {"signal": {"ref": "factor:v2:" + "a" * 43}}},
        "source_adapter": {"member_key": "source", "frequency": "MIN1"},
        "run_window": {"start": settings["start_utc"], "end": settings["end_utc"]},
        "catalog_staging": [{"paths": ["CFFEX|F|T|2403"]}],
        "session_calendar": object(),
    }
    if expected_start is None:
        with pytest.raises(ValueError, match="custom warmup starts after the run window"):
            strategy_backtest.run_strategy_family_run_spec(job_spec=job_spec, plan=plan, output_dir=tmp_path)
        assert calls == {}
        return
    result = strategy_backtest.run_strategy_family_run_spec(job_spec=job_spec, plan=plan, output_dir=tmp_path)
    assert calls["start_utc"] == expected_start
    assert calls["end_utc"] == settings["end_utc"]
    assert result["execution_plan"].start_utc == "2025-04-01T01:00:00+00:00"


def test_custom_warmup_preserves_earlier_frozen_portable_tape(monkeypatch, tmp_path):
    from tests.server.test_nautilus_bridge_config import _minimal_frozen

    class Resolver:
        def __init__(self, **kwargs): pass
        def resolve(self, **kwargs): return SimpleNamespace(expr=CLOSE)

    monkeypatch.setattr("server.modules.shared.run_spec_resolution.factors.RunFactorResolver", Resolver)
    captured = {}
    monkeypatch.setattr(
        "server.services.nautilus_bridge.catalog_staging.stage_run_spec_catalogs",
        lambda **kwargs: captured.update(kwargs) or {
            "T": {"catalog_dir": str(tmp_path), "contract_uid": "CFFEX|F|T|2403"}
        },
    )
    monkeypatch.setattr(strategy_backtest, "run_strategy_family_replay", lambda **kwargs: kwargs)
    settings = _minimal_frozen(factor_warmup={"mode": "custom", "data_start_utc": "2024-01-02T01:30:00Z"})
    job_spec = {"run_spec": {"configuration": {
        "shared": {"factors": []},
        "analyses": {"backtest": {"execution": {"nautilus_contract": {"settings": settings}}}},
    }}}
    plan = {
        "strategy": {"kind": "threshold", "parameters": {},
                     "factor_roles": {"signal": {"ref": "factor:v2:" + "a" * 43}}},
        "source_adapter": {"member_key": "source", "frequency": "MIN1"},
        "run_window": {"start": "2023-11-01T00:00:00Z", "end": settings["end_utc"]},
        "catalog_staging": [{"paths": ["CFFEX|F|T|2403"]}],
        "session_calendar": object(),
    }
    result = strategy_backtest.run_strategy_family_run_spec(job_spec=job_spec, plan=plan, output_dir=tmp_path)
    assert captured["start_utc"] == "2023-11-01T00:00:00Z"
    assert result["execution_plan"].start_utc == "2025-04-01T01:00:00+00:00"


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


def test_multiple_strategy_run_spec_resolves_same_frozen_factor_once(monkeypatch,tmp_path):
    calls=[];captured={}
    class Resolver:
        def __init__(self,**kwargs):pass
        def resolve(self,**kwargs):calls.append(kwargs);return SimpleNamespace(expr=CLOSE)
    monkeypatch.setattr('server.modules.shared.run_spec_resolution.factors.RunFactorResolver',Resolver)
    monkeypatch.setattr(strategy_backtest,'run_strategy_families_replay',lambda **kwargs:captured.update(kwargs) or {'ok':True})
    ref='factor:v2:'+'a'*43
    plan={'strategy_families':[dict(strategy_id=f'Group-{i}',kind='cross_sectional_group',
        parameters={'split_count':2,'group_index':i},factor_roles={'signal':{'ref':ref}}) for i in (1,2)],
        'catalog_inputs':{'T':{'catalog_dir':str(tmp_path),'contract_uid':'CFFEX|F|T|2403'}},'max_input_bars':8}
    result=strategy_backtest.run_strategy_family_run_spec(job_spec={'_owner':'alice','run_spec':{'configuration':{'shared':{'factors':[{'ref':ref}]}}}},plan=plan,output_dir=tmp_path/'out')
    assert result=={'ok':True} and len(calls)==1
    assert len(captured['strategies'])==2
    assert captured['strategies'][0]['factor_bindings']['signal'] is captured['strategies'][1]['factor_bindings']['signal']


def test_overlapping_netting_targets_fail_before_engine_construction(monkeypatch):
    import pytest
    instrument=SimpleNamespace(id=SimpleNamespace(venue='CFFEX',__str__=lambda self:'T.CFFEX'))
    plan=SimpleNamespace(venues=[{'name':'CFFEX','oms_type':'NETTING'}])
    monkeypatch.setattr('server.services.nautilus_bridge.engine_factory.build_backtest_engine',lambda *a,**kw:pytest.fail('no engine should be constructed'))
    with pytest.raises(ValueError,match='HEDGING'):
        strategy_backtest._build_strategy_family_engine(plan,[instrument],by_strategy={'A':[instrument],'B':[instrument]})


def test_real_transient_frozen_family_duration_window_compiles_to_shared_native_plan():
    from tests.server.test_factor_param_resolver import _frozen_probe
    from server.modules.shared.run_spec_resolution.factors import RunFactorResolver
    from tools.factors.alpha_plan import alpha_plan_spec
    from tools.data.types import DataFreq
    source="""from tools.factors import FactorFamily
from tools.data.types import DataColumn
from tools.factors.FactorExpr import ColumnRef
from tools.factors.expr.signal_align import SignalAlign
class VersionProbe(FactorFamily):
    signal_freq='30m'
    @staticmethod
    def factor_expr():
        return SignalAlign(ColumnRef(DataColumn.CLOSE).rolling('20m').mean(),'30m')
"""
    frozen={**_frozen_probe(source),'source_kind':'transient','source_code':source,'temporary':True}
    factor=RunFactorResolver(owner='alice',frozen_factors=[frozen]).resolve(factor_ref=frozen['ref'])
    spec=alpha_plan_spec(factor.expr,source_freq=DataFreq.MIN1,products=('T','TL'))
    assert spec is not None
    rolling=[x for x in spec['nodes'] if x['kind']=='rolling']
    assert len(rolling)==1 and rolling[0]['window']==20
    assert len([x for x in spec['nodes'] if x['kind']=='signal'])==2
