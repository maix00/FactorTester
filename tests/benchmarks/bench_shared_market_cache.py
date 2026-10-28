"""Isolated synthetic cache benchmark; no server, jobs or production data.

Run as a module under GTHT. RSS includes shared pages and must not be summed
to infer unique physical memory. This measures Python Arrow consumers, not
Nautilus Rust replay or browser latency.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path
import platform
import resource
import statistics
import tempfile
import time


def consume(root, source, queue):
    import pyarrow.parquet as pq
    from traderesearch_data.shared_cache import CacheScope, SharedColumnarCache
    original = pq.ParquetFile

    class Counted(original):
        def iter_batches(self, *args, **kwargs):
            with (Path(root) / 'decodes.log').open('a') as stream:
                stream.write('decode\n')
            yield from super().iter_batches(*args, **kwargs)

    pq.ParquetFile = Counted
    cache = SharedColumnarCache(Path(root), CacheScope('server', 'bench', 'platform', 'local'),
                                consumers=2, timeout=60)
    start = time.perf_counter()
    with cache.consumer():
        rows = sum(batch.num_rows for batch in cache.iter_parquet_batches(
            source, columns=['time', 'close', 'volume']))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    queue.put(dict(rows=rows, seconds=time.perf_counter()-start,
                   peak_rss_bytes=rss if platform.system() == 'Darwin' else rss*1024))


def main():
    import pyarrow as pa
    import pyarrow.parquet as pq
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=200_000)
    parser.add_argument('--processes', type=int, default=4)
    args = parser.parse_args()
    if args.rows < 1 or not 1 <= args.processes <= 16:
        parser.error('positive rows and 1..16 processes required')
    with tempfile.TemporaryDirectory(prefix='tr-shared-cache-bench-') as folder:
        root = Path(folder)/'cache'; root.mkdir()
        source = Path(folder)/'source.parquet'
        pq.write_table(pa.table({'time': range(args.rows),
                                'close': pa.array(range(args.rows), type=pa.float64()),
                                'volume': [10]*args.rows}), source, row_group_size=50_000)
        ctx = mp.get_context('spawn')
        results = dict(machine=platform.platform(), python=platform.python_version(),
                       arrow=pa.__version__, rows=args.rows, processes=args.processes,
                       source_bytes=source.stat().st_size,
                       note='cold means empty IPC cache; OS source pages are not flushed')
        for phase in ('cold', 'hot'):
            queue = ctx.Queue()
            workers = [ctx.Process(target=consume, args=(str(root), str(source), queue))
                       for _ in range(args.processes)]
            start = time.perf_counter()
            try:
                for worker in workers: worker.start()
                samples = [queue.get(timeout=90) for _ in workers]
                for worker in workers:
                    worker.join(10)
                    if worker.exitcode != 0: raise RuntimeError('worker failed')
                if any(sample['rows'] != args.rows for sample in samples):
                    raise RuntimeError('row mismatch')
                results[phase] = dict(wall_seconds=time.perf_counter()-start,
                    median_query_seconds=statistics.median(s['seconds'] for s in samples),
                    max_query_seconds=max(s['seconds'] for s in samples), samples=samples)
            finally:
                for worker in workers:
                    if worker.is_alive(): worker.terminate(); worker.join()
                queue.close()
        results['decode_scanners'] = len((root/'decodes.log').read_text().splitlines())
        results['cache_bytes'] = sum(p.stat().st_size for p in root.glob('*/*.arrow'))
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
