"""Causal signal alignment for nested factors."""

from __future__ import annotations

import pandas as pd

from .core import FactorExpr


class SignalAlign(FactorExpr):
    """Resample a factor to a lower signal frequency without look-ahead.

    The signal at target time ``t`` is the last source value with
    ``source_time <= t``; no future value is ever used.
    """

    def __init__(
        self,
        child: FactorExpr,
        signal_freq: str,
        basepoint: str = "last",
        daily_basepoint: str | None = None,
        end_session_skip: bool = False,
        end_session_gap: str | None = None,
        include_current: bool = True,
    ):
        if basepoint != "last":
            raise NotImplementedError("SignalAlign currently implements basepoint='last' only")
        if daily_basepoint is not None:
            raise NotImplementedError("daily_basepoint is an explicit SignalAlign blocker")
        if end_session_skip:
            raise NotImplementedError("end_session_skip is an explicit SignalAlign blocker")
        if end_session_gap is not None:
            raise NotImplementedError("end_session_gap is an explicit SignalAlign blocker")
        if not include_current:
            raise NotImplementedError("include_current=False is an explicit SignalAlign blocker")
        self.child = child
        self.signal_freq = str(signal_freq)
        self.basepoint = basepoint
        self.daily_basepoint = daily_basepoint
        self.end_session_skip = end_session_skip
        self.end_session_gap = end_session_gap
        self.include_current = include_current

    def _structural_key(self):
        return ("alpha.factor.SignalAlign", self.signal_freq, self.basepoint,
                self.daily_basepoint, self.end_session_skip, self.end_session_gap,
                self.include_current, self.child._structural_key())

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
