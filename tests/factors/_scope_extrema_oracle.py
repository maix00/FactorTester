"""Small exhaustive scalar oracle; deliberately independent of production kernels."""
import numpy as np


def _prefix_arg_extreme_loop(values, op, start, end, *, min_periods=1, propagate_nan=False):
    """Earliest tie; normalized age uses positions, not the count of nonmissing values.

    Only the candidate interval is subject to missing-value policy. Values after
    its endpoint cannot change the winner (including NaN at the current bar).
    Infinities are ordered values. Empty/reversed intervals return NaN.
    """
    output = np.full(len(values), np.nan, dtype=float)
    if start < 0 or (end is not None and start > end):
        return output
    for current in range(start, len(values)):
        stop = current if end is None else min(end, current)
        candidates = [(i, values[i]) for i in range(start, stop + 1)]
        valid = [(i, v) for i, v in candidates if not np.isnan(v)]
        if len(valid) < max(1, min_periods):
            continue
        if propagate_nan and len(valid) != len(candidates):
            continue
        best, value = valid[0]
        for index, challenger in valid[1:]:
            if (op == "argmax" and challenger > value) or (op == "argmin" and challenger < value):
                best, value = index, challenger
        span = current - start
        output[current] = (current - best) / span if span else 0.0
    return output
