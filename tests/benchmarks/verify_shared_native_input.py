"""Isolated Python-publisher/Rust-reader contract check, without a server.

Pass the already-built inspect_ipc executable. POSIX additionally verifies an
inherited immutable inode survives eviction before Rust opens the mapping.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

from traderesearch_data.shared_cache import CacheScope, SharedColumnarCache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader', required=True, type=Path)
    args = parser.parse_args()
    reader = str(args.reader.resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix='tr-shared-native-') as folder:
        root = Path(folder)
        source = root/'events.parquet'
        pq.write_table(pa.table({
            'event_type': pa.array(['quote', 'settlement', None]).dictionary_encode(),
            'value': pa.array([1, None, 3], type=pa.int64()),
            'levels': pa.array([[1, 2], [], None]),
        }), source)
        cache = SharedColumnarCache(root/'cache', CacheScope('server', 'test', 'platform', 'local'))
        batches = list(cache.iter_parquet_batches(source, columns=['event_type', 'value', 'levels']))
        assert sum(batch.num_rows for batch in batches) == 3
        path = next(cache.root.glob('*.arrow'))
        result = subprocess.run([reader, str(path)], check=True, capture_output=True, text=True)
        assert result.stdout.strip() == 'batches=1 rows=3', result.stdout
        if os.name == 'posix':
            with cache.borrow_chunk(path.stem) as handle:
                path.unlink()
                result = subprocess.run([reader, '--fd', str(handle.fileno())],
                    pass_fds=(handle.fileno(),), check=True, capture_output=True, text=True)
                assert result.stdout.strip() == 'batches=1 rows=3', result.stdout
            assert batches[0].column('value').to_pylist() == [1, None, 3]
        print('Python IPC → Rust mmap passed; POSIX inherited-inode check: '
              + ('passed' if os.name == 'posix' else 'not applicable'))


if __name__ == '__main__':
    main()
