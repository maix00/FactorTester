"""Canonical timeline shared by batch plan compilation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Timeline:
    index: pd.Index
    times_ns: np.ndarray
    days: np.ndarray
    observed: np.ndarray
    products: tuple[Any, ...]


def build_timeline(products, preloaded, trading_days=None) -> Timeline:
    products = tuple(products)
    frames = [frame for frame in preloaded.values() if frame is not None]
    if frames:
        index = frames[0].index
    elif trading_days is not None:
        index = pd.DatetimeIndex(trading_days)
    else:
        raise ValueError("timeline requires preloaded frames or trading days")
    if isinstance(index, pd.MultiIndex):
        times = pd.DatetimeIndex(index.get_level_values(-1)).as_unit("ns").asi8
    elif isinstance(index, pd.DatetimeIndex):
        times = index.as_unit("ns").asi8
    else:
        times = np.arange(len(index), dtype=np.int64)
    day_values = trading_days if trading_days is not None else (
        index.get_level_values(0) if isinstance(index, pd.MultiIndex) else index
    )
    if isinstance(day_values, pd.DatetimeIndex):
        day_values = day_values.normalize()
    days = pd.factorize(day_values, sort=False)[0].astype(np.int64)
    observed = np.ones((len(products), len(index)), dtype=np.uint8)
    return Timeline(index, np.ascontiguousarray(times), days, observed, products)
