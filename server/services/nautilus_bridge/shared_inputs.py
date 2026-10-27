"""Catalog → shared immutable Arrow handles; no Python event construction."""
from pathlib import Path

from traderesearch_data.shared_cache import host_input_cache


def catalog_input_handles(folder, receipt, event_type):
    """Read only receipt-listed publications in deterministic file order.

    Rust validates ts_init order and performs exact range filtering. Bundle raw
    schemas are not silently interpreted as Nautilus events here.
    """
    import pyarrow.parquet as pq
    root = Path(folder).resolve(strict=True)
    files = []
    for item in receipt['catalog_files']:
        path = (root / item['path']).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('catalog input escapes frozen root')
        type_name = item.get('type_name')
        if type_name is None:
            # Older receipts did not retain the native Arrow type metadata.
            type_name = (pq.read_schema(path).metadata or {}).get(b'type_name',b'').decode()
        if type_name == event_type:
            files.append(path)
    if not files:
        raise ValueError(f'no frozen {event_type} catalog input')
    for path in sorted(files):
        yield from host_input_cache().iter_parquet_handles(path)


def replay_shared_catalogs(engine, rows, *, chunk_size, max_chunk_events,
                           max_input_events, start, end, query_memory_limit_bytes):
    from nautilus_trader._libnautilus import replay_shared_inputs
    from nautilus_trader.model import NautilusDataType
    sources = [(NautilusDataType.Bar, catalog_input_handles(folder, receipt, 'Bar'))
               for folder, _catalog, receipt, _instrument in rows]
    sources.extend((NautilusDataType.InstrumentClose, catalog_input_handles(folder, receipt, 'InstrumentClose'))
        for folder, _catalog, receipt, _instrument in rows if receipt.get('settlement_records'))
    try:
        return replay_shared_inputs(engine, sources, chunk_size=chunk_size,
            max_chunk_events=max_chunk_events, max_input_events=max_input_events,
            max_input_batch_bytes=max(1, query_memory_limit_bytes // len(sources)),
            start=start, end=end)
    finally:
        for _kind, source in sources:
            source.close()
