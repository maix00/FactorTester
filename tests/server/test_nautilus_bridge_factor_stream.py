"""Real native Actor/consumer integration, with independent positional oracles."""
import json
import sys
from pathlib import Path
import numpy as np
import pytest
from tests.nautilus_runtime import require_nautilus
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
from server.services.nautilus_bridge.backtest_runner import _load_input, replay_catalog_batches
from server.services.nautilus_bridge.strategy_backtest import run_strategy_family_replay, _frozen_shared_plan
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup
from tools.factors.expr import CLOSE, ConstExpr, SignalAlign


def _inputs(tmp_path):
    inputs={}
    for code,month in (("T","2403"),("TL","2406")):
        folder=tmp_path/code; folder.mkdir()
        inputs[code]=_real_catalog(folder,code=code,month=month,count=8)
    return inputs


def _engine(rows):
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType, Currency, Money, OmsType, Venue
    from decimal import Decimal
    engine=BacktestEngine(config=BacktestEngineConfig(bypass_logging=True,run_analysis=False))
    engine.add_venue(venue=Venue("CFFEX"),oms_type=OmsType.NETTING,account_type=AccountType.MARGIN,
        base_currency=Currency.from_str("CNY"),starting_balances=[Money.from_str("1000000 CNY")],
        fee_model=MakerTakerFeeModel(maker_rate=Decimal(0),taker_rate=Decimal(0)))
    for row in rows: engine.add_instrument(row[3])
    return engine


def test_real_family_has_no_python_bar_callback_and_matches_asof_where(tmp_path):
    require_nautilus(); inputs=_inputs(tmp_path)
    opened=[_load_input(item) for item in inputs.values()]
    bars=[row[1].query_bars(identifiers=[row[2]["bar_type"]]) for row in opened]
    prices=np.asarray([[float(bar.close) for bar in source] for source in bars]).T
    times=np.asarray([int(bar.ts_event) for bar in bars[0]],dtype=np.int64)
    target=times//120_000_000_000*120_000_000_000
    positions=np.searchsorted(times,target,side="right")-1
    signal=np.asarray([prices[index] if index>=0 else [np.nan,np.nan] for index in positions])
    threshold=float(prices[2,0]); expected=np.where(prices>threshold,signal,-1.0)
    expression=SignalAlign(CLOSE,"2m").where(CLOSE>ConstExpr(threshold),other=ConstExpr(-1))
    calls=[]
    def profile(frame,event,arg):
        if event=="call" and frame.f_code.co_name in {"on_bar","on_signal","_bar_fields","_clock"}:
            if "nautilus_bridge" in frame.f_code.co_filename or "factors/expr/streaming" in frame.f_code.co_filename:
                calls.append((frame.f_code.co_filename,frame.f_code.co_name))
    previous=sys.getprofile();sys.setprofile(profile)
    try:
        result=run_strategy_family_replay(inputs=inputs,factor_bindings={"signal":expression,"confirm":expression},
            factor_refs={"signal":"factor:v2:fixture","confirm":"factor:v2:fixture"},
            family=CrossSectionalGroup(2,1),output_dir=tmp_path/"reports",max_bars=8,
            batch_minutes=1,trace_path=tmp_path/"factor.jsonl")
    finally: sys.setprofile(previous)
    assert calls==[]
    rows=[json.loads(line) for line in (tmp_path/"factor.jsonl").read_text().splitlines()]
    np.testing.assert_allclose(np.asarray([row["values"] for row in rows],dtype=float),expected,equal_nan=True)
    assert [row["timestamp_ns"] for row in rows]==times.tolist()
    assert [row["available_at_ns"] for row in rows]==[max(int(source[index].ts_init) for source in bars) for index in range(8)]
    assert result["factor_actors"]==1 and result["strategy_publications"]==[8]
    assert result["publications"]=={"signal":8,"confirm":8}
    assert not (Path(__file__).parents[2]/"server/services/nautilus_bridge/factor_stream.py").exists()


def test_two_strategies_share_one_plan_and_native_replay(tmp_path):
    require_nautilus()
    from nautilus_trader._libnautilus import attach_factor_family
    inputs=_inputs(tmp_path); rows=[_load_input(item) for item in inputs.values()]
    expression=CLOSE.rolling(2).semantics(min_periods=1).mean()
    spec,_=_frozen_shared_plan({"signal":expression},{"signal":"fixture"},tuple(inputs),None)
    engine=_engine(rows)
    try:
        consumers=[{"strategy_id":f"group-{index}","signal_output":0,"rule":{
            "kind":"cross_sectional_group","split_count":2,"group_index":index}} for index in (1,2)]
        runtime=attach_factor_family(engine,json.dumps(spec),list(inputs),[row[2]["bar_type"] for row in rows],json.dumps(consumers))
        result=replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1)
        runtime.ensure_success()
        assert result["bars"]==16
        assert runtime.node_count==2 and runtime.slice_count==8
        assert runtime.consumer_counts==[8,8]
        assert runtime.rank_passes==8
        assert len(set(engine.generate_fills_report()["strategy_id"].astype(str)))==2
    finally: engine.dispose()


def test_native_actor_session_reset_and_missing_calendar_failure(tmp_path):
    require_nautilus()
    from nautilus_trader._libnautilus import attach_factor_family
    inputs=_inputs(tmp_path); rows=[_load_input(item) for item in inputs.values()]
    bars=[row[1].query_bars(identifiers=[row[2]["bar_type"]]) for row in rows]
    times=[int(bar.ts_event) for bar in bars[0]]
    plan={"columns":["CLOSE"],"boundaries":["trading_day_start"],"nodes":[
        {"kind":"column","index":0},{"kind":"boundary","index":0},
        {"kind":"session_reset","child":0,"boundary":1,"op":"mean","min_periods":1,"propagate_nan":False}],"outputs":[2]}
    consumers=[{"strategy_id":"threshold-1","signal_output":0,"rule":{
        "kind":"threshold","entry":1000,"exit":0,"side_mode":"long_short"}}]
    for short in (False,True):
        engine=_engine(rows)
        try:
            # Deliberately synthetic split within real prices, not exchange session evidence.
            calendar=[[times[0]-60_000_000_000,times[3]],[times[3]+1,times[4] if short else times[-1]]]
            trace=tmp_path/f"reset-{short}.jsonl"
            runtime=attach_factor_family(engine,json.dumps(plan),list(inputs),[row[2]["bar_type"] for row in rows],json.dumps(consumers),json.dumps(calendar),str(trace))
            if short:
                with pytest.raises(ValueError,match="count differs"):
                    replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1)
                with pytest.raises(RuntimeError,match="outside.*calendar"):runtime.raise_if_failed()
            else:
                replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1); runtime.ensure_success()
                actual=np.asarray([json.loads(line)["values"] for line in trace.read_text().splitlines()])
                expected=[[np.mean([float(bar.close) for bar in source[(0 if i<4 else 4):i+1]]) for source in bars] for i in range(8)]
                np.testing.assert_allclose(actual,expected)
        finally:engine.dispose()


def test_native_intermediate_lookup_reads_existing_latest_slot(tmp_path):
    import pytest
    from alpha.factor import ColumnRef, compile_factor_outputs
    from nautilus_trader._libnautilus import attach_factor_family
    require_nautilus()
    inputs=_inputs(tmp_path);rows=[_load_input(item) for item in inputs.values()]
    mean=ColumnRef('CLOSE').rolling(2).semantics(min_periods=1).mean().as_intermediate('mean')
    outer=mean+mean
    plain,_,_=compile_factor_outputs({'signal':outer},tuple(inputs))
    spec,_,_=compile_factor_outputs({'signal':outer},tuple(inputs),intermediates=('mean',))
    assert len(spec['nodes'])==len(plain['nodes'])==3
    engine=_engine(rows)
    try:
        consumers=[{'strategy_id':'query-1','signal_output':0,'rule':{
            'kind':'threshold','entry':1,'exit':0,'side_mode':'long_only'}}]
        runtime=attach_factor_family(engine,json.dumps(spec),list(inputs),
            [row[2]['bar_type'] for row in rows],json.dumps(consumers))
        with pytest.raises(RuntimeError,match='no factor output'):
            runtime.latest_output(spec['intermediates']['mean'])
        replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1)
        runtime.ensure_success()
        ts,available,values=runtime.latest_output(spec['intermediates']['mean'])
        bars=[row[1].query_bars(identifiers=[row[2]['bar_type']]) for row in rows]
        expected=[np.mean([float(bar.close) for bar in source[-2:]]) for source in bars]
        np.testing.assert_allclose(values,expected)
        np.testing.assert_allclose(runtime.latest_output(0)[2],np.asarray(expected)*2)
        assert ts==int(bars[0][-1].ts_event)
        assert available==max(int(source[-1].ts_init) for source in bars)
        for _ in range(10):
            assert runtime.latest_output(1)==(ts,available,values)
        assert runtime.slice_count==8 and runtime.node_count==3
        with pytest.raises(RuntimeError,match='outside plan'):
            runtime.latest_output(100)
    finally:
        engine.dispose()
