"""Retained scalar oracle for regression/benchmark comparison; never production."""
import numpy as np

def _prefix_arg_extreme_loop(
    values: np.ndarray, op: str, start: int, end: int,
) -> np.ndarray:
    """逐根实现：小分区下比 numpy 调用开销更低，同时作为向量化版的等价参照。"""
    length = len(values)
    output = np.full(length, np.nan, dtype=float)
    best_index = start
    stop = length - 1 if end is None else min(end, length - 1)
    scanned_through = start
    for position in range(start, length):
        limit = position if end is None else min(position, stop)
        for challenger in range(scanned_through + 1, limit + 1):
            challenger_value = values[challenger]
            if np.isnan(challenger_value):
                continue
            best_value = values[best_index] if best_index >= 0 else np.nan
            # 只有严格更优才推进，保证与 rolling 的「最早出现的极值」一致。
            if np.isnan(best_value) or (
                (op == "argmax" and challenger_value > best_value)
                or (op == "argmin" and challenger_value < best_value)
            ):
                best_index = challenger
        scanned_through = max(scanned_through, limit)
        if np.isnan(values[position]) or np.isnan(values[best_index]):
            continue
        span = position - start
        age = position - best_index
        output[position] = 0.0 if span == 0 else age / span
    return output
