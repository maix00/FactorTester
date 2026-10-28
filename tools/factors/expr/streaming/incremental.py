"""Thin FactorTester adapter to the shared Rust factor plan; no Python DAG state."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from tools.data.types import DataFreq
from tools.factors.expr.core import FactorExpr

LAST_RUST_PLAN_ERROR: str | None = None

class UnsupportedStreamingFactor(ValueError):
    pass


class NormalizedBarFields(dict[str, float]):
    """Internal marker for the native snapshot's string/numeric field map."""

    __slots__ = ()


class SingleFactorIncrementalExecutor:
    """Compatibility facade: one alias over the shared multi-factor executor."""

    def __init__(self, factor_alias: str, multi: Any) -> None:
        self.factor_alias = factor_alias
        self._multi = multi
        self._plan = multi._plan

    def on_bar(self, *args, **kwargs) -> None:
        self._multi.on_bar(*args, **kwargs)

    def on_signal(self, timestamp: pd.Timestamp) -> dict[Any, float]:
        return dict(self._multi.on_signal(timestamp)[self.factor_alias])


def compile_incremental_factor(
    factor_alias: str,
    expression: FactorExpr,
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
    session_calendar: Any = None,
    event_line: Any = None,
    require_rust: bool = False,
) -> SingleFactorIncrementalExecutor:
    """Compile one author-facing FactorExpr into a run-scoped executor."""

    multi = compile_incremental_factors(
        {factor_alias: expression}, products, source_freq=source_freq,
        session_calendar=session_calendar, event_line=event_line,
        require_rust=require_rust,
    )
    return SingleFactorIncrementalExecutor(factor_alias, multi)


def last_rust_plan_error() -> str | None:
    return LAST_RUST_PLAN_ERROR


def compile_incremental_factors(
    expressions: dict[str, FactorExpr],
    products: tuple[Any, ...],
    *,
    source_freq: DataFreq | str | None = None,
    session_calendar: Any = None,
    event_line: Any = None,
    require_rust: bool = False,
):
    """Compile several factors into one shared Rust incremental DAG."""
    if not expressions:
        raise ValueError("incremental factor set must be non-empty")
    from tools.factors.expr.streaming.rust_incremental import compile_rust_incremental
    global LAST_RUST_PLAN_ERROR
    try:
        LAST_RUST_PLAN_ERROR = None
        return compile_rust_incremental(
            expressions, products, source_freq=source_freq,
            session_calendar=session_calendar, event_line=event_line,
        )
    except Exception as error:
        LAST_RUST_PLAN_ERROR = f"{type(error).__name__}: {error}"
        raise


def resolve_trading_day_window(
    value: object,
    *,
    calendar_window: Any,
    current_session: int,
) -> int:
    """Resolve a session lookback (e.g. ``250d``) to its minute-bar count.

    The count is variable: it is the sum of authoritative session bar counts
    over the requested trading-day lookback.  It must be recomputed at every
    session boundary, never approximated as a fixed multiple of calendar days.
    """
    if isinstance(value, str):
        duration = pd.Timedelta(value)
    elif isinstance(value, pd.Timedelta):
        duration = value
    else:
        raise UnsupportedStreamingFactor("trading-day windows must be durations")
    if duration < pd.Timedelta("1D"):
        raise UnsupportedStreamingFactor("trading-day window must span at least one day")
    ratio = duration / pd.Timedelta("1D")
    if not np.isfinite(ratio) or not np.isclose(ratio, round(ratio)):
        raise UnsupportedStreamingFactor("trading-day window must be an integer day count")
    return calendar_window.window_size(current_session, int(round(ratio)))


def _event_ref_from_window(value: object):
    """Parse explicit ``event:<id>`` window syntax into an EventRef."""
    if not isinstance(value, str) or not value.startswith("event:"):
        return None
    from tools.factors.events import EventId, EventRef, Occurrence

    parts = value.split(":")
    if len(parts) == 3 and parts[1] in {item.value for item in Occurrence}:
        return EventRef(EventId(parts[2]), Occurrence(parts[1]))
    return EventRef(EventId(parts[1]))


def _resolve_window_bars(
    value: object,
    source_freq: DataFreq | str | None,
) -> int:
    if isinstance(value, (int, np.integer)):
        bars = int(value)
    elif isinstance(value, (pd.Timedelta, str)):
        if source_freq is None:
            raise UnsupportedStreamingFactor(
                "duration windows require an explicit source frequency"
            )
        duration = pd.Timedelta(value)
        frequency = DataFreq(source_freq).value
        if duration >= pd.Timedelta("1D") and frequency < pd.Timedelta("1D"):
            raise UnsupportedStreamingFactor(
                "session-spanning duration windows require a trading-calendar kernel"
            )
        ratio = duration / frequency
        if not np.isfinite(ratio) or not np.isclose(ratio, round(ratio)):
            raise UnsupportedStreamingFactor(
                f"window {duration} is not an integer multiple of {frequency}"
            )
        bars = round(ratio)
    else:
        raise UnsupportedStreamingFactor("streaming windows must resolve to fixed bars")
    if bars <= 0:
        raise UnsupportedStreamingFactor("streaming window must be positive")
    return bars
