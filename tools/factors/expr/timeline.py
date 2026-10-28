"""FactorTester source-metadata adapter to alpha.factor's canonical timeline."""
from __future__ import annotations
import pandas as pd
from alpha.factor.timeline import (
    Timeline, build_timeline, from_observed, compact_observed, scatter_observed,
    union_index as _union_index, same_observed_slots as _has_same_observed_slots,
)
from tools.data.types import DataIndex, finest_index


class PanelTimeline(Timeline):
    """Adapt the historical labelled constructor; all grid behavior is shared."""
    def __init__(self, index, products, trading_days, observed_mask, same_session):
        timeline = from_observed(index, products, trading_days, observed_mask,
                                 times=_timestamps(index).as_unit("ns").asi8, same_session=same_session)
        super().__init__(timeline.index, timeline.times_ns, timeline.days, timeline.observed,
                         timeline.products, timeline.day_labels, timeline._same_session)


def build_panel_timeline(products, freq, preloaded):
    return build_timeline(products, preloaded, frequency=freq.name,
                          day_resolver=_trading_days,
                          time_resolver=lambda index: _timestamps(index).as_unit("ns").asi8)


def _timestamps(index):
    return pd.DatetimeIndex(finest_index(index) if isinstance(index, pd.MultiIndex) else index)


def _trading_days(index):
    return pd.Index(DataIndex.trading_day_index_from_index(index), name="DAY1")
