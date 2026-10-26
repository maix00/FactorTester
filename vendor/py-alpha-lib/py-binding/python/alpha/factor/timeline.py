"""Canonical source timeline/grid metadata, independent of FactorTester."""
from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
from typing import Any
import numpy as np
import pandas as pd


def timestamps_ns(index):
    values = index.get_level_values(-1) if isinstance(index, pd.MultiIndex) else index
    return (np.ascontiguousarray(values.as_unit("ns").asi8) if isinstance(values, pd.DatetimeIndex)
            else np.arange(len(index), dtype=np.int64))


def union_index(frames):
    index = None
    for frame in frames:
        index = frame.index if index is None else index.union(frame.index)
    return pd.Index([]) if index is None else index.sort_values()


def same_observed_slots(observed):
    values = observed.to_numpy(dtype=bool) if isinstance(observed, pd.DataFrame) else np.asarray(observed, dtype=bool).T
    return values.shape[1] < 2 or bool(np.all(values == values[:, [0]]))


@dataclass(frozen=True)
class Timeline:
    index: pd.Index
    times_ns: np.ndarray
    days: np.ndarray
    observed: np.ndarray
    products: tuple[Any, ...]
    day_labels: pd.Index | None = None
    _same_session: bool | None = None

    @cached_property
    def observed_mask(self):
        return pd.DataFrame(self.observed.T.view(np.bool_), index=self.index, columns=self.products, copy=False)

    @property
    def trading_days(self):
        return self.day_labels if self.day_labels is not None else pd.Index(self.days)

    @cached_property
    def same_session(self):
        return self._same_session if self._same_session is not None else same_observed_slots(self.observed)

    @cached_property
    def dense_same_session(self):
        return bool(self.same_session and self.observed.size and self.observed.all())

    def align(self, index, columns):
        labels = pd.Series(np.asarray(self.trading_days), index=self.index).reindex(index)
        if labels.isna().any():
            raise ValueError("aligned timeline contains unknown trading-day labels")
        mask = self.observed_mask.reindex(index=index, columns=columns, fill_value=False)
        times = pd.Series(self.times_ns, index=self.index).reindex(index)
        return from_observed(index, columns, labels.to_numpy(), mask, times=times.to_numpy(dtype=np.int64))


def from_observed(index, products, trading_days, observed, *, times=None, same_session=None):
    labels = pd.Index(trading_days)
    if len(labels) != len(index):
        raise ValueError("trading-day labels must match source rows")
    if isinstance(observed, pd.DataFrame):
        mask = observed.to_numpy(dtype=bool, copy=False).T
    else:
        mask = np.asarray(observed)
        mask = mask.view(np.bool_) if mask.dtype == np.uint8 else mask.astype(bool, copy=False)
    if mask.shape != (len(products), len(index)):
        raise ValueError("observation grid must match products and source rows")
    mask = np.ascontiguousarray(mask).view(np.uint8)
    return Timeline(index, timestamps_ns(index) if times is None else np.ascontiguousarray(times, dtype=np.int64),
                    pd.factorize(labels, sort=False)[0].astype(np.int64), mask, tuple(products), labels, same_session)


def build_timeline(products, preloaded, trading_days=None, *, frequency=None, day_resolver=None, time_resolver=None):
    products = tuple(products)
    frames = {}
    for product in products:
        frame = preloaded.get(product)
        if frame is None:
            frame = preloaded.get((product, frequency))
        if frame is None and frequency is None:
            candidates = [value for key, value in preloaded.items() if isinstance(key, tuple) and key[0] == product]
            if len(candidates) > 1:
                raise ValueError("multiple source frequencies require an explicit frequency")
            frame = candidates[0] if candidates else None
        if frame is not None:
            frames[product] = frame
    index = union_index(frames.values())
    if not len(index) and trading_days is not None:
        index = pd.DatetimeIndex(trading_days)
    if trading_days is None:
        if day_resolver is not None:
            trading_days = day_resolver(index)
        else:
            trading_days = index.get_level_values(0) if isinstance(index, pd.MultiIndex) else index
            if isinstance(trading_days, pd.DatetimeIndex):
                trading_days = trading_days.normalize()
    if isinstance(trading_days, pd.Series):
        trading_days = trading_days.reindex(index).to_numpy()
    observed = np.zeros((len(products), len(index)), dtype=np.uint8)
    for position, product in enumerate(products):
        if product in frames:
            observed[position] = index.isin(frames[product].index)
    return from_observed(index, products, trading_days, observed,
                         times=None if time_resolver is None else time_resolver(index))


def compact_observed(data, timeline):
    observed = timeline.observed_mask.reindex(index=data.index, columns=data.columns, fill_value=False).to_numpy(dtype=bool)
    ordinals = np.cumsum(observed, axis=0, dtype=int) - 1
    counts = observed.sum(axis=0, dtype=int)
    packed = np.full((int(counts.max()) if counts.size else 0, data.shape[1]), np.nan)
    rows, columns = np.nonzero(observed)
    if packed.size:
        packed[ordinals[rows, columns], columns] = data.to_numpy(dtype=float)[rows, columns]
    return pd.DataFrame(packed, columns=data.columns), ordinals, observed


def scatter_observed(packed, template, ordinals, observed):
    result = np.full(template.shape, np.nan)
    if packed.size:
        rows, columns = np.nonzero(observed)
        result[rows, columns] = packed.to_numpy(dtype=float)[ordinals[rows, columns], columns]
    return pd.DataFrame(result, index=template.index, columns=template.columns)
