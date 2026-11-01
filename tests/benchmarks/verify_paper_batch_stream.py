"""Compare the frozen paper factor on real Bars in batch and incremental Rust.

Diagnostic only: no orders, P&L, remote Job or performance acceptance. A nonzero
exit code reports unequal values; neither implementation is assumed correct.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factors', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--product', required=True)
    parser.add_argument('--formal-start', required=True)
    parser.add_argument('--suffix-start', help='compare a second replay starting at this warmup timestamp')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    from alpha import FactorPlanState
    from alpha.algo import _algo
    from server.modules.shared.factor_param_resolver import _resolve_frozen_factor
    from sources.LocalCNFutures.CNFutures import get_all_futures
    from tools.data.types import DataFreq, finest_index
    from tools.factors.alpha_plan import alpha_plan_spec
    from tools.factors.expr.core import EvaluateContext
    from tools.factors.expr.rust_plan import evaluate_rust_plan
    from tools.factors.expr.streaming.calendar_window import TradingCalendarWindow, TradingSession
    from tools.factors.expr.timeline import PanelTimeline

    products = [product for product in get_all_futures() if product.name == args.product]
    if len(products) != 1:
        raise ValueError('expected one registered product')
    product = products[0]
    frozen = json.loads(args.factors.read_text())
    refs = {item['ref']: item for item in frozen['factors']}
    factor = _resolve_frozen_factor(refs[frozen['signal_ref']], username='alice', frozen_by_ref=refs)
    frame = pq.read_table(args.source, columns=['trade_timestamp', 'trading_day', 'close_price',
        'adjustment_mul', 'adjustment_add']).to_pandas()
    times = frame.trade_timestamp.to_numpy(dtype=np.int64) * 1_000_000
    days = frame.trading_day.to_numpy()
    if not len(times) or np.any(times[1:] <= times[:-1]):
        raise ValueError('source observation times must be strictly increasing')
    price = frame.close_price.to_numpy(dtype=float)
    adjusted = price * frame.adjustment_mul.to_numpy() + frame.adjustment_add.to_numpy()
    starts = np.r_[0, np.flatnonzero(days[1:] != days[:-1]) + 1]
    ends = np.r_[starts[1:], len(times)]
    if len(pd.unique(days)) != len(starts):
        raise ValueError('source trading days must form contiguous sessions')
    sessions = [TradingSession(str(days[a]), int(times[a]) - 60_000_000_000,
                               int(times[b - 1]), int(b - a)) for a, b in zip(starts, ends)]
    index = pd.MultiIndex.from_arrays([pd.to_datetime(days), pd.to_datetime(times, utc=True)],
                                      names=['DAY1', 'MIN1'])
    values = pd.DataFrame({'CLOSE': price, 'CLOSE_ADJUSTED': adjusted}, index=index)
    timeline = PanelTimeline(index=index, products=(product,), trading_days=pd.Index(days),
                             observed_mask=pd.DataFrame(True, index=index, columns=[product]), same_session=True)
    ctx = EvaluateContext(products=[product], freq=DataFreq.MIN1,
                          preloaded={(product, DataFreq.MIN1.name): values}, cache={}, panel_timeline=timeline)
    started = time.perf_counter()
    batch = evaluate_rust_plan([factor.expr], ctx)
    batch_seconds = time.perf_counter() - started
    if batch is None:
        raise ValueError('batch factor is not supported')
    batch = batch[0]
    batch_times = pd.DatetimeIndex(finest_index(batch.index) if isinstance(batch.index, pd.MultiIndex)
                                   else batch.index).as_unit('ns').asi8
    spec = alpha_plan_spec(factor.expr, source_freq=DataFreq.MIN1, products=(product,),
                           session_calendar=TradingCalendarWindow(tuple(sessions)))
    if spec is None:
        raise ValueError('incremental factor is not supported')
    if set(spec['columns']) - {'CLOSE', 'CLOSE_ADJUSTED'}:
        raise ValueError('diagnostic source does not supply all factor columns')
    state = FactorPlanState(json.dumps({key: value for key, value in spec.items() if key != 'key_tuples'}), 1)
    row = np.empty(len(spec['columns']))
    boundary = np.zeros(len(spec['boundaries']), dtype=np.uint8)
    incremental = np.empty(len(times))
    started = time.perf_counter()
    for i in range(len(times)):
        for j, column in enumerate(spec['columns']):
            row[j] = adjusted[i] if column == 'CLOSE_ADJUSTED' else price[i]
        boundary[:] = i == 0 or days[i] != days[i - 1]
        incremental[i] = state.update_context(int(times[i]), row, boundary)[0]
    incremental_seconds = time.perf_counter() - started
    formal_start = pd.Timestamp(args.formal_start)
    if formal_start.tzinfo is None:
        raise ValueError('formal start must include a time zone')
    positions = np.searchsorted(times, batch_times)
    formal = batch_times >= formal_start.value
    matched = (positions < len(times)) & (times[np.minimum(positions, len(times) - 1)] == batch_times)
    mask = formal & matched
    if not mask.any() or np.any(formal & ~matched):
        raise ValueError('formal batch signals cannot all be matched to source Bars')
    batch_values = batch[product].to_numpy()[mask]
    increment_values = incremental[positions[mask]]
    different = ~np.isclose(batch_values, increment_values, equal_nan=True, rtol=1e-9, atol=1e-8)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform.startswith('linux'):
        peak_rss *= 1024
    result = {
        'source_sha256': digest(args.source), 'factor_sha256': digest(args.factors),
        'alpha_extension_sha256': digest(Path(_algo.__file__)), 'product': args.product,
        'rows': len(times), 'trading_days': len(starts), 'formal_start': args.formal_start,
        'source_start_utc': pd.Timestamp(times[0], unit='ns', tz='UTC').isoformat(),
        'source_end_utc': pd.Timestamp(times[-1], unit='ns', tz='UTC').isoformat(),
        'batch_signal_rows_compared': int(mask.sum()), 'mismatches': int(different.sum()),
        'batch_nonfinite': int((~np.isfinite(batch_values)).sum()),
        'incremental_nonfinite': int((~np.isfinite(increment_values)).sum()),
        'batch_diagnostic_seconds': batch_seconds, 'incremental_diagnostic_seconds': incremental_seconds,
        'process_peak_rss_bytes': int(peak_rss),
        'limitation': 'factor-only diagnostic, not a trading backtest or remote Job; time excludes data loading',
    }
    suffix_mismatch = False
    if args.suffix_start:
        suffix_start = pd.Timestamp(args.suffix_start)
        if suffix_start.tzinfo is None or suffix_start >= formal_start:
            raise ValueError('suffix start must be timezone-aware and precede formal start')
        first = int(np.searchsorted(times, suffix_start.value))
        state = FactorPlanState(json.dumps({key: value for key, value in spec.items() if key != 'key_tuples'}), 1)
        suffix = np.empty(len(times) - first)
        started = time.perf_counter()
        for i in range(first, len(times)):
            for j, column in enumerate(spec['columns']):
                row[j] = adjusted[i] if column == 'CLOSE_ADJUSTED' else price[i]
            boundary[:] = i == first or days[i] != days[i - 1]
            suffix[i - first] = state.update_context(int(times[i]), row, boundary)[0]
        formal_positions = np.flatnonzero(times >= formal_start.value)
        suffix_different = ~np.isclose(incremental[formal_positions], suffix[formal_positions - first],
                                       equal_nan=True, rtol=1e-9, atol=1e-8)
        suffix_mismatch = bool(suffix_different.any())
        result['suffix_comparison'] = {
            'requested_start': args.suffix_start, 'source_ordinal': first,
            'formal_bar_rows_compared': len(formal_positions),
            'mismatches': int(suffix_different.sum()),
            'diagnostic_seconds': time.perf_counter() - started,
        }
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    if different.any():
        raise SystemExit('batch and incremental factor values differ')
    if suffix_mismatch:
        raise SystemExit('factor values depend on the warmup replay start')


if __name__ == '__main__':
    main()
