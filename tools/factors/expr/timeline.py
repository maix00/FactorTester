from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools.data.DataFreq import DataFreq


@dataclass(frozen=True)
class PanelTimeline:
    index: pd.Index
    products: tuple[Any, ...]
    trading_days: pd.Index
    observed_mask: pd.DataFrame
    scheduled_mask: pd.DataFrame
    missing_schedule_products: tuple[Any, ...]
    same_session: bool | None

    @property
    def schedule_complete(self) -> bool:
        return not self.missing_schedule_products

    @property
    def dense_same_session(self) -> bool:
        return bool(
            self.schedule_complete
            and self.same_session
            and not self.observed_mask.empty
            and self.observed_mask.to_numpy(dtype=bool).all()
        )

    def align(self, index: pd.Index, columns: Sequence[Any]) -> 'PanelTimeline':
        return PanelTimeline(
            index=index,
            products=tuple(columns),
            trading_days=_trading_days(index),
            observed_mask=self.observed_mask.reindex(index=index, columns=columns, fill_value=False),
            scheduled_mask=self.scheduled_mask.reindex(index=index, columns=columns, fill_value=False),
            missing_schedule_products=tuple(p for p in columns if p in self.missing_schedule_products),
            same_session=self.same_session,
        )


def build_panel_timeline(
    products: Sequence[Any],
    freq: DataFreq,
    preloaded: Mapping[tuple[Any, str], pd.DataFrame],
) -> PanelTimeline:
    index = _union_index(preloaded.values())
    products_tuple = tuple(products)
    timestamps = _timestamps(index)
    observed = pd.DataFrame(False, index=index, columns=products_tuple, dtype=bool)
    scheduled = pd.DataFrame(False, index=index, columns=products_tuple, dtype=bool)
    missing: list[Any] = []
    schedule_keys: list[Any] = []

    for product in products_tuple:
        data = preloaded.get((product, freq.name))
        if data is not None:
            observed[product] = index.isin(data.index)

        if freq.is_day_multiple():
            scheduled[product] = True
            schedule_keys.append(("day",))
            continue

        get_schedule = getattr(product, "get_trading_schedule", None)
        schedule = get_schedule() if callable(get_schedule) else None
        if schedule is None:
            missing.append(product)
            continue
        scheduled[product] = np.asarray(schedule.contains_timestamps(timestamps), dtype=bool)
        schedule_keys.append(schedule.sessions)

    same_session = None if missing else len(set(schedule_keys)) <= 1
    return PanelTimeline(
        index=index,
        products=products_tuple,
        trading_days=_trading_days(index),
        observed_mask=observed,
        scheduled_mask=scheduled,
        missing_schedule_products=tuple(missing),
        same_session=same_session,
    )


def _union_index(frames) -> pd.Index:
    index: pd.Index | None = None
    for frame in frames:
        index = frame.index if index is None else index.union(frame.index)
    if index is None:
        return pd.Index([])
    return index.sort_values()


def _timestamps(index: pd.Index) -> pd.DatetimeIndex:
    values = index.get_level_values(-1) if isinstance(index, pd.MultiIndex) else index
    return pd.DatetimeIndex(values)


def _trading_days(index: pd.Index) -> pd.Index:
    if isinstance(index, pd.MultiIndex) and "DAY1" in index.names:
        return pd.Index(index.get_level_values("DAY1"), name="DAY1")
    return pd.Index(_timestamps(index).normalize(), name="DAY1")


# ── session-aware shift lookup ──

def shift_positions(
    timeline: PanelTimeline,
    periods: int,
    data: pd.DataFrame,
) -> pd.DataFrame:
    """Return a DataFrame of lookup positions for session-aware shift(periods).

    Each cell contains the integer row position of the value ``periods``
    scheduled bars earlier for that product, or -1 when no such bar exists
    (including when the source bar is scheduled but unobserved).

    Pure intraday periods: count only ``scheduled_mask == True`` slots.
    Day mixed periods: locate the trading-day boundary first, then apply
    intraday remainder on ``scheduled_mask``.

    On dense same-session panels this is *not* called — the caller uses the
    standard pandas ``.shift(periods)`` fast path.
    """
    result = pd.DataFrame(-1, index=data.index, columns=data.columns, dtype=int)
    scheduled = timeline.scheduled_mask.reindex(index=data.index, columns=data.columns, fill_value=False)
    observed = timeline.observed_mask.reindex(index=data.index, columns=data.columns, fill_value=False)

    for col in data.columns:
        mask = scheduled[col].to_numpy(dtype=bool)
        pos = np.arange(len(mask))
        # -- find scheduled positions for each row --
        scheduled_pos = np.where(mask)[0]
        if len(scheduled_pos) == 0:
            continue
        # for each scheduled position, its ordinal index
        ordinal_map = np.full(len(mask), -1, dtype=int)
        ordinal_map[scheduled_pos] = np.arange(len(scheduled_pos))
        for i in range(len(mask)):
            if not mask[i]:
                continue
            target_ord = ordinal_map[i] - periods
            if target_ord < 0:
                continue
            src_pos = scheduled_pos[target_ord]
            # scheduled but unobserved → leave as -1 (=NaN in shift result)
            if not observed[col].iloc[src_pos]:
                continue
            result.iloc[i, result.columns.get_loc(col)] = src_pos
    return result
