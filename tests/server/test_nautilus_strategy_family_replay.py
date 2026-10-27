from __future__ import annotations

from tests.nautilus_runtime import require_nautilus
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
from server.services.nautilus_bridge.strategy_backtest import run_strategy_family_replay
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup, ThresholdState
from tools.factors.expr import CLOSE


def test_real_group_strategy_runs_across_two_products(tmp_path, monkeypatch):
    require_nautilus()
    import pytest
    pytest.importorskip("pyarrow")
    (tmp_path / "T").mkdir()
    (tmp_path / "TL").mkdir()
    inputs = {
        "T": _real_catalog(tmp_path / "T", code="T", month="2403"),
        "TL": _real_catalog(tmp_path / "TL", code="TL", month="2406"),
    }
    from server.services.nautilus_bridge import backtest_runner
    assert not hasattr(backtest_runner, "iter_catalog_bar_batches")
    result = run_strategy_family_replay(
        inputs=inputs, factor_bindings={"signal": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=CrossSectionalGroup(split_count=2, group_index=1),
        output_dir=tmp_path / "group-reports", max_bars=8, batch_minutes=3,
    )
    assert result["products"] == ["T", "TL"]
    assert result["bars"] == 16
    assert result["publications"] == {"signal": 8}
    assert result["factor_actors"] == 1
    assert result["python_factor_bar_callbacks"] == 0
    assert result["strategy_publications"] == [8]
    assert result["batch_count"] >= 2
    assert result["max_batch_bars"] <= 6
    assert result["orders"] >= 1
    assert (tmp_path / "group-reports" / "tearsheet.html").is_file()


def test_real_threshold_family_consumes_signal_and_creates_orders(tmp_path):
    require_nautilus()
    result = run_strategy_family_replay(
        inputs={"T": _real_catalog(tmp_path, count=8)},
        factor_bindings={"signal": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=ThresholdState(entry=1, exit=0),
        output_dir=tmp_path / "threshold-reports", max_bars=8,
    )
    assert result["publications"] == {"signal": 8}
    assert result["factor_actors"] == 1
    assert result["python_factor_bar_callbacks"] == 0
    assert result["strategy_publications"] == [8]
    assert result["orders"] == 1


def test_unsupported_python_family_cannot_register_a_callback(tmp_path):
    import pytest
    require_nautilus()
    class PythonFamily:
        def direction(self, value):
            raise AssertionError("Python decision must never execute")
    with pytest.raises(ValueError, match="unsupported native"):
        run_strategy_family_replay(
            inputs={"T": _real_catalog(tmp_path,count=8)}, factor_bindings={"signal":CLOSE},
            factor_refs={"signal":"factor:v2:" + "a"*43}, family=PythonFamily(),
            output_dir=tmp_path/"invalid-reports", max_bars=8)
    assert not (tmp_path/"invalid-reports").exists()


def test_two_real_group_strategies_share_factor_state_and_ranking(tmp_path):
    from server.services.nautilus_bridge.strategy_backtest import run_strategy_families_replay
    require_nautilus()
    for p in ('T','TL'):(tmp_path/p).mkdir()
    inputs={'T':_real_catalog(tmp_path/'T',code='T',month='2403',count=32),
            'TL':_real_catalog(tmp_path/'TL',code='TL',month='2406',count=32)}
    mean=CLOSE.rolling(20).semantics(min_periods=1).mean()
    ref='factor:v2:'+'a'*43
    strategies=[dict(strategy_id=f'Group-{i}',factor_bindings={'signal':mean},factor_refs={'signal':ref},
                     family=CrossSectionalGroup(2,i)) for i in (1,2)]
    result=run_strategy_families_replay(inputs=inputs,strategies=strategies,output_dir=tmp_path/'reports',max_bars=32,batch_minutes=8)
    assert result['factor_actors']==1 and result['factor_plan_nodes']==2
    assert result['strategy_publications']==[32,32]
    assert result['rank_passes']==32  # not once per strategy
    assert result['python_factor_bar_callbacks']==0
    assert result['bars']==64 and result['orders']==2
    assert result['strategy_output_slots']=={'Group-1':{'signal':0},'Group-2':{'signal':0}}


def test_real_consumers_cannot_trade_outside_their_frozen_product_scope(tmp_path):
    from server.services.nautilus_bridge.strategy_backtest import run_strategy_families_replay
    import pandas as pd
    require_nautilus()
    for p in ('T','TL'):(tmp_path/p).mkdir()
    inputs={'T':_real_catalog(tmp_path/'T',code='T',month='2403'),
            'TL':_real_catalog(tmp_path/'TL',code='TL',month='2406')}
    strategies=[dict(strategy_id=f'Scope-{i}',factor_bindings={'signal':CLOSE},
        factor_refs={'signal':'factor:v2:'+'a'*43},family=ThresholdState(1,0),products=[p])
        for i,p in enumerate(('T','TL'))]
    result=run_strategy_families_replay(inputs=inputs,strategies=strategies,output_dir=tmp_path/'reports',max_bars=8)
    assert result['strategy_publications']==[8,8] and result['orders']==2
    fills=pd.read_csv(tmp_path/'reports/fills.csv')
    assert len(fills)==2
    assert len(fills['instrument_id'].unique())==2


def test_conflicting_frozen_factor_ref_rejected_before_loading_inputs(monkeypatch,tmp_path):
    from server.services.nautilus_bridge import strategy_backtest as module
    import pytest
    require_nautilus()
    monkeypatch.setattr(module,'_load_input',lambda *a:pytest.fail('must reject before reading'))
    strategies=[dict(strategy_id=f'Strategy-{i}',factor_bindings={'signal':expr},
        factor_refs={'signal':'factor:v2:'+'a'*43},family=ThresholdState(1,0))
        for i,expr in enumerate((CLOSE,CLOSE+1))]
    with pytest.raises(ValueError,match='conflicting expressions'):
        module.run_strategy_families_replay(inputs={'T':None},strategies=strategies,output_dir=tmp_path)


def test_real_cross_factor_uses_each_strategy_universe(tmp_path):
    from server.services.nautilus_bridge.strategy_backtest import run_strategy_families_replay
    require_nautilus()
    for p in ('T','TL'):(tmp_path/p).mkdir()
    inputs={'T':_real_catalog(tmp_path/'T',code='T',month='2403'),
            'TL':_real_catalog(tmp_path/'TL',code='TL',month='2406')}
    expression=CLOSE.cs_rank()
    strategies=[dict(strategy_id=f'Cross-{i}',products=[p],factor_bindings={'signal':expression},
        factor_refs={'signal':'factor:v2:'+'a'*43},family=ThresholdState(.25,0))
        for i,p in enumerate(('T','TL'))]
    result=run_strategy_families_replay(inputs=inputs,strategies=strategies,output_dir=tmp_path/'reports',max_bars=8,inspect_outputs=True)
    assert result['orders']==2  # both singleton ranks are .5; a global rank would trade only one
    assert result['strategy_output_slots']=={'Cross-0':{'signal':0},'Cross-1':{'signal':1}}
    import numpy as np
    np.testing.assert_equal(result['latest_outputs']['Cross-0']['signal'][2],[.5,np.nan])
    np.testing.assert_equal(result['latest_outputs']['Cross-1']['signal'][2],[np.nan,.5])
