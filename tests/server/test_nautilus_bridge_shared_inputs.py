"""Local input sharing and actual native engine equivalence; no server jobs."""
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from traderesearch_data.shared_cache import CacheScope, SharedColumnarCache
from server.services.nautilus_bridge import shared_inputs


@pytest.fixture(autouse=True)
def isolated_host_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('TR_SHARED_DATA_CACHE_ROOT', str(tmp_path/'host-cache'))


def test_handles_share_python_buffers_without_python_batch_decode(tmp_path, monkeypatch):
    cache = SharedColumnarCache(tmp_path/'cache', CacheScope('server','test','platform','local'))
    path = tmp_path/'events.parquet'
    schema = pa.schema([('value',pa.int64())], metadata={b'type_name':b'Bar'})
    pq.write_table(pa.Table.from_arrays([pa.array([1,2,3])], schema=schema),path)
    receipt = {'catalog_files':[{'path':path.name}]}
    monkeypatch.setattr(shared_inputs, 'host_input_cache', lambda: cache)
    expected = list(cache.iter_parquet_batches(path, columns=['value']))
    publications = {p.name:p.stat().st_ino for p in cache.root.glob('*.arrow')}
    opened = list()
    # Warm native handle reads must not reconstruct IPC batches in Python.
    monkeypatch.setattr(pa.ipc, 'open_file', lambda *_: pytest.fail('unexpected Python IPC decode'))
    for handle in shared_inputs.catalog_input_handles(tmp_path, receipt, 'Bar'):
        opened.append(handle)
        assert not handle.closed
    assert all(handle.closed for handle in opened)
    assert {p.name:p.stat().st_ino for p in cache.root.glob('*.arrow')} == publications
    assert expected[0].column('value').to_pylist() == [1,2,3]


def test_catalog_handle_source_rejects_escape_and_missing_type(tmp_path):
    folder = tmp_path/'catalog'; folder.mkdir()
    pq.write_table(pa.table({'value':[1]}), tmp_path/'other.parquet')
    with pytest.raises(ValueError, match='escapes'):
        list(shared_inputs.catalog_input_handles(folder,
            {'catalog_files':[{'path':'../other.parquet'}]},'Bar'))
    with pytest.raises(ValueError, match='no frozen'):
        list(shared_inputs.catalog_input_handles(folder, {'catalog_files':[]},'Bar'))


def test_source_counters_follow_native_config_order_with_two_settlements():
    from types import SimpleNamespace
    from server.services.nautilus_bridge.backtest_runner import replay_catalog_batches
    rows = [(Path('/unused'),None,{'bar_type':f'{code}2403.CFFEX-1-MINUTE-LAST-EXTERNAL',
        'selected_count':8,'first_available_ns':1,'last_available_ns':8,
        'settlement_records':[{'event_ns':8}]},SimpleNamespace(id=f'{code}2403.CFFEX'))
        for code in ['T','TL']]
    engine = SimpleNamespace(run_catalogs=lambda **_: (18,4,8,[8,8,1,1]),
                             get_result=lambda: SimpleNamespace(iterations=18))
    result = replay_catalog_batches(engine,rows,max_input_bars=16)
    assert result['bars'] == 16 and result['settlements'] == 2


def test_actual_shared_replay_matches_catalog_engine(tmp_path, monkeypatch):
    import json
    from nautilus_trader import _libnautilus as native
    assert callable(getattr(native,'replay_shared_inputs',None)), 'rebuild composed Nautilus extension'
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
    from tests.server.test_nautilus_bridge_factor_stream import _engine
    from server.services.nautilus_bridge.backtest_runner import _load_input, replay_catalog_batches
    from server.services.nautilus_bridge.strategy_backtest import _frozen_shared_plan
    from tools.factors.expr import CLOSE
    cache = SharedColumnarCache(tmp_path/'cache', CacheScope('server','test','platform','local'))
    monkeypatch.setattr(shared_inputs, 'host_input_cache', lambda: cache)
    rows = []
    for code, month in [('T','2403'),('TL','2406')]:
        folder = tmp_path/code; folder.mkdir()
        rows.append(_load_input(_real_catalog(folder,code=code,month=month,count=8)))
    results = []
    products = ['T','TL']
    plan, _ = _frozen_shared_plan({'signal':CLOSE.rolling(2).semantics(min_periods=1).mean()},
                                {'signal':'fixture'},tuple(products),None)
    for transport in ['catalog','shared','shared']:
        engine = _engine(rows)
        try:
            runtime = native.attach_factor_family(engine,json.dumps(plan),products,
                [row[2]['bar_type'] for row in rows],json.dumps([{
                    'strategy_id':'group-1','signal_output':0,'rule':{
                        'kind':'cross_sectional_group','split_count':2,'group_index':1}}]))
            result = replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1,
                                            input_transport=transport)
            runtime.ensure_success()
            fills = engine.generate_fills_report()
            fill_rows = [(str(row['instrument_id']),str(row['order_side']),str(row['last_qty']),str(row['last_px']))
                         for _,row in fills.iterrows()]
            results.append((result, engine.get_result().iterations, runtime.latest_output(0),fill_rows))
        finally:
            engine.dispose()
    assert results[0] == results[1] == results[2]
    assert results[0][1] == 16
    assert results[0][3], 'actual strategy must trade'
    assert list(cache.root.glob('*.arrow'))


def test_actual_nautilus_replay_consumes_data_io_socket_handles(tmp_path, monkeypatch):
    import json
    import threading
    import time
    from nautilus_trader import _libnautilus as native
    from server.data_io.service import DataIOService
    from server.services.nautilus_bridge.backtest_runner import _load_input, replay_catalog_batches
    from server.services.nautilus_bridge.strategy_backtest import _frozen_shared_plan
    from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
    from tests.server.test_nautilus_bridge_factor_stream import _engine
    from tools.factors.expr import CLOSE

    if not callable(getattr(native, 'replay_shared_inputs', None)):
        pytest.skip('requires the locally rebuilt composed Nautilus extension')
    cache = SharedColumnarCache(tmp_path/'cache', CacheScope('server','test','platform','local'))
    monkeypatch.setattr(shared_inputs, 'host_input_cache', lambda: cache)
    rows = []
    for code, month in [('T','2403'),('TL','2406')]:
        folder = tmp_path/code; folder.mkdir()
        rows.append(_load_input(_real_catalog(folder,code=code,month=month,count=8)))

    socket_path = tmp_path/'run'/'data.sock'
    service = DataIOService(socket_path=socket_path, allowed_roots=[tmp_path],
                            cache_factory=lambda: cache, max_requests=2)
    server = service.bind()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    monkeypatch.setenv('TR_DATA_IO_SOCKET_PATH', str(socket_path))
    products = ['T','TL']
    plan, _ = _frozen_shared_plan(
        {'signal':CLOSE.rolling(2).semantics(min_periods=1).mean()},
        {'signal':'fixture'},tuple(products),None)
    engine = _engine(rows)
    try:
        runtime = native.attach_factor_family(engine,json.dumps(plan),products,
            [row[2]['bar_type'] for row in rows],json.dumps([{
                'strategy_id':'group-1','signal_output':0,'rule':{
                    'kind':'cross_sectional_group','split_count':2,'group_index':1}}]))
        result = replay_catalog_batches(engine,rows,max_input_bars=16,batch_minutes=1,
                                        input_transport='shared')
        runtime.ensure_success()
        assert result['bars'] == 16
        assert engine.get_result().iterations == 16
        assert not engine.generate_fills_report().empty
        assert len(list(cache.root.glob('*.arrow'))) >= 2
    finally:
        engine.dispose()
        server.shutdown()
        server.server_close()
        socket_path.unlink(missing_ok=True)
        thread.join(timeout=2)


def test_actual_shared_invalid_inputs_fail_before_loading():
    from nautilus_trader import _libnautilus as native
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.model import NautilusDataType
    assert callable(getattr(native,'replay_shared_inputs',None)), 'rebuild composed Nautilus extension'
    engine = BacktestEngine(config=BacktestEngineConfig(bypass_logging=True,run_analysis=False))
    try:
        with pytest.raises(RuntimeError, match='unsupported shared input'):
            native.replay_shared_inputs(engine,[(NautilusDataType.OrderBookDelta,iter([None]))],1,10,10)
        with pytest.raises(RuntimeError, match='chunk bounds'):
            native.replay_shared_inputs(engine,[(NautilusDataType.Bar,iter([None]))],0,10,10)
        with pytest.raises(RuntimeError, match='start must not follow end'):
            native.replay_shared_inputs(engine,[(NautilusDataType.Bar,iter([None]))],1,10,10,start=2,end=1)
        with pytest.raises(RuntimeError, match='byte budget'):
            native.replay_shared_inputs(engine,[(NautilusDataType.Bar,iter([None]))],1,10,10,max_input_batch_bytes=0)
        assert engine.get_result().iterations == 0
    finally:
        engine.dispose()
