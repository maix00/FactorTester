"""Causal signal alignment for nested factors."""

from __future__ import annotations

import pandas as pd

from .core import FactorExpr


class SignalAlign(FactorExpr):
    """Resample a factor to a lower signal frequency without look-ahead.

    The signal at target time ``t`` is the last source value with
    ``source_time <= t``; no future value is ever used.
    """

    def __init__(self, child: FactorExpr, signal_freq: str, basepoint: str = "last"):
        if basepoint != "last":
            raise NotImplementedError(
                "alpha.factor SignalAlign currently supports basepoint='last' only; "
                "first/daily/end_session_skip remain explicit blockers"
            )
        self.child = child
        self.signal_freq = str(signal_freq)
        self.basepoint = basepoint

    def _structural_key(self):
        return ("alpha.factor.SignalAlign", self.signal_freq, self.basepoint,
                self.child._structural_key())

    def evaluate(self, ctx) -> pd.DataFrame:
        source = self.child.evaluate(ctx)
        if isinstance(source.index, pd.MultiIndex):
            signal_levels = [
                index for index, name in enumerate(source.index.names)
                if str(name).startswith("_SIGNAL@")
            ]
            if not signal_levels:
                raise TypeError("nested SignalAlign requires a _SIGNAL@ level")
            times = pd.DatetimeIndex(
                source.index.get_level_values(signal_levels[-1]),
            )
        elif isinstance(source.index, pd.DatetimeIndex):
            times = source.index
        else:
            raise TypeError("SignalAlign requires a DatetimeIndex source")
        target = pd.date_range(
            times[0].ceil(self.signal_freq),
            times[-1],
            freq=self.signal_freq,
        )
        from alpha import BatchPlan
        positions = BatchPlan.asof_indices(
            times.as_unit("ns").asi8,
            target.as_unit("ns").asi8,
        )
        import numpy as np
        positions = np.asarray(positions, dtype=np.int64)
        valid = positions >= 0
        out = {}
        for product in source.columns:
            values = source[product].to_numpy(dtype=float)
            aligned = np.full(len(positions), np.nan, dtype=float)
            aligned[valid] = values[positions[valid]]
            out[product] = aligned
        return pd.DataFrame(out, index=target)


def _method(self, signal_freq: str, basepoint: str = "last"):
    return SignalAlign(self, signal_freq, basepoint)


FactorExpr.signal_align = _method
