from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools.data.types import finest_index
from tools.data.types import DataFreq


@dataclass(frozen=True)
class PanelTimeline:
    index: pd.Index
    products: tuple[Any, ...]
    trading_days: pd.Index
    observed_mask: pd.DataFrame
    same_session: bool

    @property
    def dense_same_session(self) -> bool:
        return bool(
            self.same_session
            and not self.observed_mask.empty
            and self.observed_mask.to_numpy(dtype=bool).all()
        )

    def align(self, index: pd.Index, columns: Sequence[Any]) -> 'PanelTimeline':
        observed = self.observed_mask.reindex(index=index, columns=columns, fill_value=False)
        return PanelTimeline(
            index=index,
            products=tuple(columns),
            trading_days=_trading_days(index),
            observed_mask=observed,
            same_session=_has_same_observed_slots(observed),
        )


def build_panel_timeline(
    products: Sequence[Any],
    freq: DataFreq,
    preloaded: Mapping[tuple[Any, str], pd.DataFrame],
) -> PanelTimeline:
    index = _union_index(preloaded.values())
    products_tuple = tuple(products)
    observed = pd.DataFrame(False, index=index, columns=products_tuple, dtype=bool)
    for product in products_tuple:
        data = preloaded.get((product, freq.name))
        if data is not None:
            observed[product] = index.isin(data.index)
    return PanelTimeline(
        index=index,
        products=products_tuple,
        trading_days=_trading_days(index),
        observed_mask=observed,
        same_session=_has_same_observed_slots(observed),
    )


def compact_observed(
    data: pd.DataFrame,
    timeline: PanelTimeline,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Pack each product's observed bars into a dense column matrix."""
    observed = timeline.observed_mask.reindex(
        index=data.index, columns=data.columns, fill_value=False,
    ).to_numpy(dtype=bool)
    ordinals = np.cumsum(observed, axis=0, dtype=int) - 1
    counts = observed.sum(axis=0, dtype=int)
    max_count = int(counts.max()) if counts.size else 0
    packed = np.full((max_count, data.shape[1]), np.nan, dtype=float)
    if packed.size:
        rows, cols = np.nonzero(observed)
        packed[ordinals[rows, cols], cols] = data.to_numpy(dtype=float)[rows, cols]
    return pd.DataFrame(packed, columns=data.columns), ordinals, observed


def scatter_observed(
    packed: pd.DataFrame,
    template: pd.DataFrame,
    ordinals: np.ndarray,
    observed: np.ndarray,
) -> pd.DataFrame:
    result = np.full(template.shape, np.nan, dtype=float)
    if packed.size:
        rows, cols = np.nonzero(observed)
        result[rows, cols] = packed.to_numpy(dtype=float)[ordinals[rows, cols], cols]
    return pd.DataFrame(result, index=template.index, columns=template.columns)


def _has_same_observed_slots(observed: pd.DataFrame) -> bool:
    values = observed.to_numpy(dtype=bool)
    return values.shape[1] < 2 or bool(np.all(values == values[:, [0]]))


def _union_index(frames) -> pd.Index:
    index: pd.Index | None = None
    for frame in frames:
        index = frame.index if index is None else index.union(frame.index)
    if index is None:
        return pd.Index([])
    return index.sort_values()


def _timestamps(index: pd.Index) -> pd.DatetimeIndex:
    values = finest_index(index) if isinstance(index, pd.MultiIndex) else index
    return pd.DatetimeIndex(values)


def _trading_days(index: pd.Index) -> pd.Index:
    """交易日层与数据层同一权威：优先日级层，否则事件时间的自然日。

    日级层的判定（``DAY1``、``trading_day``、``_SIGNAL@DAY1`` 等）统一交给
    ``DataIndex``，因子层不再自认「名字必须恰为 DAY1」——否则名字不同的面板会
    静默退回日历日，夜盘 bar 就会被归到错误的交易日。
    """
    from tools.data.types import DataIndex

    return pd.Index(DataIndex.trading_day_index_from_index(index), name="DAY1")
