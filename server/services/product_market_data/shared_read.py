"""Server-side shared input buffers; client hosts construct their own scope.

This server convenience entrypoint never imports a client plugin or pulls a
client source remotely; client hosts construct an explicit separate scope.
Request authorization remains at the HTTP/data-source boundary, not the cache.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path

from traderesearch_data.shared_cache import CacheBusy, CacheLimit, CacheScope, SharedColumnarCache
from .errors import ProductMarketDataError


def server_input_cache():
    from traderesearch_data.shared_cache import host_input_cache
    return host_input_cache(expected_role="server")


def chart_request(function):
    @wraps(function)
    def run(*args, **kwargs):
        try:
            with server_input_cache().consumer():
                return function(*args, **kwargs)
        except CacheBusy as exc:
            raise ProductMarketDataError('行情查询繁忙，请稍后重试', 429) from exc
        except CacheLimit as exc:
            raise ProductMarketDataError('行情查询超过资源上限，请缩短范围或选择更粗频率', 413) from exc
    return run


def parquet_frame(path, *, columns, filters=(), max_bytes=128*1024**2,
                  transform=None, combine=None):
    """Project/filter first; optional chart folding keeps coarse views bounded."""
    import pandas as pd
    frames, size = [], 0
    for batch in server_input_cache().iter_parquet_batches(path, columns=columns, filters=filters):
        if not batch.num_rows:
            continue
        frame = batch.to_pandas(split_blocks=True)
        if transform is not None:
            frame = transform(frame)
        frames.append(frame)
        size += int(frame.memory_usage(index=True, deep=True).sum())
        if size > 1024*1024 and combine is not None:
            frames = [combine(pd.concat(frames))]
            size = int(frames[0].memory_usage(index=True, deep=True).sum())
        if size > max_bytes:
            raise CacheLimit('projected frame exceeds per-query byte budget')
    if not frames:
        return pd.DataFrame(columns=columns)
    result = pd.concat(frames) if len(frames) > 1 else frames[0]
    return combine(result) if combine is not None else result
