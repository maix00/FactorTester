"""Small isolated checks; no production data, jobs or server traffic."""
from pathlib import Path
import multiprocessing
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from traderesearch_data.shared_cache import CacheBusy, CacheScope, SharedColumnarCache


def _scope(role='server', owner='platform'):
    return CacheScope(role, 'test-authority', owner, 'test-device')


def _file(path, n=1000):
    pq.write_table(pa.table({'value': list(range(n)), 'other': [1]*n}), path,
                   row_group_size=n)


def test_mmap_cache_reuse_projection_and_batch_bound(tmp_path):
    source = tmp_path/'source.parquet'; _file(source)
    cache = SharedColumnarCache(tmp_path/'cache', _scope())
    first = list(cache.iter_parquet_batches(source, columns=['value'], batch_size=100))
    entries = list(cache.root.glob('*.arrow'))
    assert len(entries) == 1
    inode = entries[0].stat().st_ino
    second = list(cache.iter_parquet_batches(source, columns=['value'], batch_size=3))
    assert max(b.num_rows for b in second) <= 3
    assert pa.Table.from_batches(first).equals(pa.Table.from_batches(second))
    assert entries[0].stat().st_ino == inode
    assert first[0].schema.names == ['value']


def test_cache_scope_isolation_and_global_admission(tmp_path):
    source=tmp_path/'source.parquet'; _file(source)
    server=SharedColumnarCache(tmp_path/'cache', _scope(), consumers=1, timeout=0)
    client=SharedColumnarCache(tmp_path/'cache', _scope('client','alice'), consumers=1, timeout=0)
    list(server.iter_parquet_batches(source, columns=['value']))
    list(client.iter_parquet_batches(source, columns=['value']))
    assert server.root != client.root
    assert len(list((tmp_path/'cache').glob('*/*.arrow'))) == 2
    with server.consumer():
        with pytest.raises(CacheBusy):
            with client.consumer():
                pytest.fail('cross-process host budget was bypassed')


def test_byte_and_entry_budgets_evict_without_invalidating_borrowed_buffers(tmp_path):
    cache=SharedColumnarCache(tmp_path/'cache', _scope(), max_bytes=16_384,
                              max_entry_bytes=4096, max_entries=2)
    borrowed=None
    for number in range(4):
        path=tmp_path/f'{number}.parquet'; _file(path, 20)
        batches=list(cache.iter_parquet_batches(path, columns=['value']))
        if borrowed is None: borrowed=batches
    entries=list(cache.base.glob('*/*.arrow'))
    assert len(entries) <= 2
    assert sum(p.stat().st_size for p in entries) <= 16_384
    assert borrowed[0].column('value').to_pylist() == list(range(20))
    assert not list(cache.base.glob('*/*.reserve'))
    assert not list(cache.base.glob('*/*.partial'))


def test_large_row_group_is_cached_in_bounded_chunks(tmp_path):
    source=tmp_path/'large.parquet'; _file(source, 1000)
    cache=SharedColumnarCache(tmp_path/'cache',_scope(),max_bytes=64*1024,max_entry_bytes=32*1024)
    batches=list(cache.iter_parquet_batches(source,columns=['value'],batch_size=7))
    assert sum(b.num_rows for b in batches) == 1000
    assert max(b.num_rows for b in batches) <= 7
    assert len(list(cache.root.glob('*.arrow'))) == 1


def test_source_replacement_does_not_reuse_old_data(tmp_path):
    source=tmp_path/'source.parquet'; _file(source, 10)
    cache=SharedColumnarCache(tmp_path/'cache',_scope())
    assert sum(b.num_rows for b in cache.iter_parquet_batches(source,columns=['value'])) == 10
    replacement=tmp_path/'new.parquet'; _file(replacement, 20);os.replace(replacement,source)
    assert sum(b.num_rows for b in cache.iter_parquet_batches(source,columns=['value'])) == 20
    assert len(list(cache.root.glob('*.arrow'))) == 2


def test_borrowed_chunk_uses_open_inode_and_validates_identity(tmp_path):
    source = tmp_path/'source.parquet'; _file(source, 10)
    cache = SharedColumnarCache(tmp_path/'cache', _scope())
    list(cache.iter_parquet_batches(source, columns=['value']))
    path = next(cache.root.glob('*.arrow'))
    with pytest.raises(ValueError):
        with cache.borrow_chunk('../outside'): pass
    with cache.borrow_chunk(path.stem) as handle:
        with pa.ipc.open_file(handle) as reader:
            assert reader.read_all().column('value').to_pylist() == list(range(10))
        assert not handle.closed
    assert handle.closed


def _worker(root, source, event, queue):
    # Count actual decodes, not just the number of published files.
    original = pq.ParquetFile
    class Counted(original):
        def iter_batches(self, *args, **kwargs):
            with (Path(root)/'decodes.log').open('a') as log: log.write('decode\n')
            yield from super().iter_batches(*args, **kwargs)
    pq.ParquetFile=Counted
    cache=SharedColumnarCache(Path(root),_scope(),consumers=2,timeout=15)
    event.wait(15)
    try:
        with cache.consumer():
            rows=sum(batch.num_rows for batch in cache.iter_parquet_batches(source,columns=['value']))
        queue.put(('ok',rows))
    except Exception as exc:
        queue.put(('error',repr(exc)))


def test_spawned_processes_decode_one_shared_input_once(tmp_path):
    source=tmp_path/'source.parquet'; _file(source, 10000)
    root=tmp_path/'cache'; root.mkdir()
    ctx=multiprocessing.get_context('spawn'); event=ctx.Event();queue=ctx.Queue()
    workers=[ctx.Process(target=_worker,args=(str(root),str(source),event,queue)) for _ in range(4)]
    for worker in workers: worker.start()
    event.set()
    try:
        results=[queue.get(timeout=30) for _ in workers]
        assert results == [('ok',10000)]*4
        for worker in workers:
            worker.join(10);assert worker.exitcode == 0
        assert (root/'decodes.log').read_text().splitlines() == ['decode']
        assert len(list(root.glob('*/*.arrow'))) == 3
    finally:
        for worker in workers:
            if worker.is_alive(): worker.terminate();worker.join(5)
        queue.close()


def test_web_slot_is_reserved_while_batch_input_is_busy(tmp_path):
    cache=SharedColumnarCache(tmp_path/'cache',_scope(),consumers=2,timeout=0)
    with cache.consumer(interactive=False):
        with pytest.raises(CacheBusy):
            with cache.consumer(interactive=False):
                pytest.fail('batch work consumed reserved web capacity')
        with cache.consumer(interactive=True):
            pass


def test_filters_use_shared_blocks_and_skip_unrelated_row_groups(tmp_path):
    source=tmp_path/'source.parquet'
    pq.write_table(pa.table({'value':list(range(40))}),source,row_group_size=10)
    cache=SharedColumnarCache(tmp_path/'cache',_scope())
    batches=list(cache.iter_parquet_batches(source,columns=['value'],
        filters=[('value','>=',11),('value','<=',13)]))
    assert pa.Table.from_batches(batches).column('value').to_pylist() == [11,12,13]
    assert len(list(cache.root.glob('*.arrow'))) == 1


def test_partial_publication_is_cleaned_and_retry_is_possible(tmp_path, monkeypatch):
    source=tmp_path/'source.parquet';_file(source)
    cache=SharedColumnarCache(tmp_path/'cache',_scope())
    original=pq.ParquetFile
    class Broken(original):
        def iter_batches(self,*args,**kwargs):
            raise RuntimeError('synthetic decode failure')
            yield
    monkeypatch.setattr(pq,'ParquetFile',Broken)
    with pytest.raises(RuntimeError,match='synthetic'):
        list(cache.iter_parquet_batches(source,columns=['value']))
    assert not list(cache.base.glob('*/*.reserve'))
    assert not list(cache.base.glob('*/*.partial'))
    monkeypatch.setattr(pq,'ParquetFile',original)
    assert sum(b.num_rows for b in cache.iter_parquet_batches(source,columns=['value'])) == 1000
