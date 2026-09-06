# =============================================================================
# tools/factors/expr/signal_align.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
import threading
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, NamedTuple,
    Optional, Sequence, Set, Tuple, Union, cast
)

from tools.data.types import DataColumn
from tools.data.types import finest_index
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .composite import CompositeExpr


class _IndexLevelFreq(NamedTuple):
    pos: int
    name: str
    freq: DataFreq


def _coerce_tuple_index(data: pd.DataFrame) -> pd.DataFrame:
    index = data.index
    if isinstance(index, pd.MultiIndex) or len(index) == 0:
        return data
    first = index[0]
    if not isinstance(first, tuple) or len(first) == 0:
        return data
    tuple_len = len(first)
    if not all(isinstance(value, tuple) and len(value) == tuple_len for value in index):
        return data
    result = data.copy(deep=False)
    result.index = pd.MultiIndex.from_tuples(index)
    return result


def _positive_freq_from_name(name: Any) -> DataFreq | None:
    try:
        freq = DataFreq(name)
    except Exception:
        return None
    if freq.value <= pd.Timedelta(0):
        return None
    return freq


def _infer_positive_freq_from_level(index: pd.Index, level_pos: int) -> DataFreq | None:
    if isinstance(index, pd.MultiIndex):
        values = index.get_level_values(level_pos)
    else:
        values = index
    try:
        timestamps = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
    except Exception:
        return None
    timestamps = timestamps[~timestamps.isna()]
    if len(timestamps) < 2:
        return None
    # Product data is already ordered by event time in the normal runtime
    # path.  The former ``unique().sort_values()`` allocated a hash table and
    # then sorted the entire two-year minute index on every expression
    # evaluation.  Adjacent differences are equivalent for a monotonic index;
    # retain a sorted fallback only for unusual out-of-order inputs.
    # Pandas 3 may store a DatetimeIndex in microseconds (or another native
    # resolution); ``asi8`` is expressed in that native unit, not always ns.
    # Keep the unit alongside the integer differences so inferred frequencies
    # are not accidentally scaled by 1,000 or 1,000,000.
    values_raw = timestamps.asi8
    if not timestamps.is_monotonic_increasing:
        values_raw = np.sort(values_raw)
    positive = np.diff(values_raw)
    positive = positive[positive > 0]
    if positive.size == 0:
        return None
    return DataFreq(pd.Timedelta(int(positive.min()), unit=getattr(timestamps, "unit", "ns")))


def _index_level_freqs(
    index: pd.Index,
    *,
    target_freq: DataFreq | None = None,
) -> list[_IndexLevelFreq]:
    """Resolve time levels, avoiding a full timestamp scan when possible.

    Product panels commonly carry a business-named trading-day level together
    with an explicitly named event level such as ``MIN1``.  The old resolver
    inferred *every* unnamed level before selecting the level compatible with
    ``target_freq``.  On a two-year minute panel that meant repeatedly doing a
    full ``unique().sort_values()`` over hundreds of thousands of timestamps
    for a level that could never be the signal level.  Resolve named levels
    first and, when one is already compatible with the requested frequency,
    skip inference for the remaining levels.  The fallback inference remains
    intact for business-named or otherwise unnamed indexes.
    """
    names = list(index.names) if isinstance(index, pd.MultiIndex) else [index.name]
    resolved: list[_IndexLevelFreq] = []
    unresolved: list[tuple[int, str]] = []
    for pos, raw_name in enumerate(names):
        name = str(raw_name)
        freq = _positive_freq_from_name(name)
        if freq is None:
            unresolved.append((pos, name))
        else:
            resolved.append(_IndexLevelFreq(pos, name, freq))
    if target_freq is not None and any(
        target_freq.value.total_seconds() % level.freq.value.total_seconds() == 0
        for level in resolved
    ):
        return resolved
    # For sub-day targets the right-most unresolved level is the event-time
    # level in the product-panel contract.  Try it first and stop as soon as
    # it is compatible; scanning a repeated trading-day level before every
    # high-frequency expression evaluation needlessly rebuilds large indexes.
    # Day-level targets must retain the original left-to-right selection rule
    # because a coarser DAY1 level should win over an event-time level.
    if target_freq is not None and not target_freq.is_day_multiple():
        for pos, name in reversed(unresolved):
            freq = _infer_positive_freq_from_level(index, pos)
            if freq is None:
                continue
            resolved.append(_IndexLevelFreq(pos, name, freq))
            if target_freq.value.total_seconds() % freq.value.total_seconds() == 0:
                return sorted(resolved, key=lambda item: item.pos)

    # Preserve the old exhaustive fallback for daily targets and unusual
    # indexes where the event-time level is not the right-most one.
    seen = {item.pos for item in resolved}
    for pos, name in unresolved:
        if pos in seen:
            continue
        freq = _infer_positive_freq_from_level(index, pos)
        if freq is not None:
            resolved.append(_IndexLevelFreq(pos, name, freq))
    return sorted(resolved, key=lambda item: item.pos)


def _named_time_index(data: pd.DataFrame, level_freqs: Sequence[_IndexLevelFreq]) -> tuple[pd.DataFrame, list[str]]:
    index = data.index
    names = list(index.names) if isinstance(index, pd.MultiIndex) else [index.name]
    freq_by_pos = {level.pos: level.freq.name for level in level_freqs}
    used: dict[str, int] = {}
    resolved: list[str] = []
    for pos, raw_name in enumerate(names):
        if raw_name is None:
            name = freq_by_pos.get(pos, f"level_{pos}")
        else:
            name = str(raw_name)
        count = used.get(name, 0)
        used[name] = count + 1
        if count:
            name = f"{name}_{count}"
        resolved.append(name)
    if list(names) == resolved:
        return data, resolved
    result = data.copy(deep=False)
    result.index = result.index.set_names(resolved)
    return result, resolved


def signal_align(
    data: pd.DataFrame,
    freq: Any,
    basepoint: 'str|Callable' = 'last',
    daily_basepoint: 'str|None' = None,
    end_session_skip: bool = False,
    end_session_gap: pd.Timedelta = cast(pd.Timedelta, pd.Timedelta('3hours')),
) -> pd.DataFrame:
    """
    将原始数据对齐到等间隔信号时间点。

    参数：
        data           : 待对齐的 DataFrame（列=Product，行=MultiIndex 时间）
        freq           : 目标信号频率（如 '1d', '1h'）
        basepoint      : 基准点选择策略 'last'/'first'/callable
        daily_basepoint: 日倍频时的具体时间基准点（如 '15:00:00'），None 用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效）
        end_session_gap: 盘间间隔阈值

    返回：
        对齐后的 DataFrame，索引含 _SIGNAL@ 层级
    """
    import pandas as pd
    freq_dc = DataFreq(freq)
    bp = basepoint
    end_skip = end_session_skip
    end_gap = end_session_gap
    data = _coerce_tuple_index(data)

    # 找到 freq 是其整数倍的索引层级（第一个匹配的）
    level_freqs = _index_level_freqs(data.index, target_freq=freq_dc)
    data, index_names = _named_time_index(data, level_freqs)
    try:
        aligned_level = next(
            level
            for level in level_freqs
            if freq_dc.value.total_seconds() % level.freq.value.total_seconds() == 0
        )
    except StopIteration:
        raise ValueError(
            f"频率 {freq_dc} 不是任何数据索引频率的整数倍")
    first_true_idx = aligned_level.pos
    multiple = int(freq_dc.value.total_seconds() / aligned_level.freq.value.total_seconds())

    idx_name = index_names[first_true_idx]
    idx_series = data.index.get_level_values(idx_name).to_series().reset_index(drop=True)

    # 确定各组的基准点位置
    if freq_dc.is_day_multiple and daily_basepoint is not None:
        try:
            bp_ts = pd.Timestamp(daily_basepoint)
            base_time = getattr(bp_ts, 'time')()
        except Exception:
            raise ValueError(
                f"Invalid time basepoint '{daily_basepoint}'. "
                f"Must be a time string like '09:01:00' or '15:00:00'")
        # Mark rows whose innermost timestamp matches the requested basepoint time.
        # NOTE: we deliberately produce a boolean Series (not a DataFrame) so the
        # downstream basepoint selection logic stays consistent.
        last_level = finest_index(data.index)
        times = pd.DatetimeIndex(last_level)
        series = pd.Series(times.time == base_time)
    elif isinstance(bp, str):
        bp_lower = bp.lower()
        if bp_lower == 'last':
            series = data.groupby(idx_name).cumcount(ascending=False) == 0
        elif bp_lower == 'first':
            series = data.groupby(idx_name).cumcount() == 0
        else:
            raise ValueError(
                f"Invalid basepoint '{bp}'. Must be 'last', 'first', or a callable")
    else:
        series = bp(data.groupby(idx_name))

    if not any(series):
        series = data.groupby(idx_name).cumcount(ascending=False) == 0
    assert isinstance(series, pd.Series) and series.dtype == bool, \
        "basepoint function must return a boolean Series"

    bp_series: pd.Series = cast(pd.Series, series)
    basepoint_pos: pd.Series = cast(pd.Series, bp_series.reset_index(drop=True).index[bp_series])

    # 从基准点按 multiple 间隔取信号点
    if end_skip and isinstance(freq_dc.value, pd.Timedelta) and freq_dc.value < pd.Timedelta('1day'):
        last_col_name = index_names[-1]
        last_col: pd.Series = cast(pd.Series, data.index.get_level_values(last_col_name).to_series().reset_index(drop=True))
        _last_col_filtered: pd.Series = cast(pd.Series, last_col[last_col.shift(-1) - last_col >= end_gap])
        end_session_pos: pd.Index = cast(pd.Index, _last_col_filtered.index)
        session_ends = end_session_pos.tolist() + [len(last_col) - 1]
        signal_map_mask = cast(pd.Series, basepoint_pos.isin({
            i
            for start, end in zip(
                [0] + [int(pos) + 1 for pos in end_session_pos],
                session_ends,
            )
            for i in range(start + multiple - 1, end + 1, multiple)
            if start + multiple - 1 <= end
        }))
    else:
        idx: pd.Series = cast(pd.Series, basepoint_pos.to_series().reset_index(drop=True).index)
        signal_map_mask = cast(pd.Series, idx % multiple == multiple - 1)

    signal_pos: pd.Series = cast(pd.Series, basepoint_pos[cast(pd.Series, signal_map_mask)])
    signal_map = cast(pd.Series, idx_series.index.isin(signal_pos))

    # 构建新的索引
    # 过滤掉旧的 _SIGNAL@ 层级 — 确保新索引中只有一个 _SIGNAL@ 列
    signal_name = f'_SIGNAL@{freq_dc.name}'
    _SIGNAL_PREFIX = '_SIGNAL@'
    left_arrays = [
        data.index.get_level_values(index_names[i]).to_series().where(signal_map)
        for i in range(first_true_idx)
        if not str(index_names[i]).startswith(_SIGNAL_PREFIX)
    ]
    signal_vals = idx_series.where(signal_map)
    right_arrays = [
        data.index.get_level_values(index_names[i]).to_series()
        for i in range(first_true_idx + 1, len(index_names))
        if not str(index_names[i]).startswith(_SIGNAL_PREFIX)
    ]
    left_names = [str(n).split('@')[-1] for n in index_names[:first_true_idx]
                  if not str(n).startswith(_SIGNAL_PREFIX)]
    right_names = [str(n).split('@')[-1] for n in index_names[first_true_idx + 1:]
                   if not str(n).startswith(_SIGNAL_PREFIX)]
    new_index = pd.MultiIndex.from_arrays(
        left_arrays + [signal_vals] + right_arrays,
        names=left_names + [signal_name] + right_names
    ).dropna()

    result = cast(pd.DataFrame, data[cast(pd.Series, signal_map)]).copy()
    result.index = new_index
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐表达式节点
# ═════════════════════════════════════════════════════════════════════════════

class SignalAlign(CompositeExpr):
    """
    信号对齐表达式节点 — 作为 CompositeExpr 的一元运算。

    将操作数表达式的求值结果对齐到等间隔信号时间点。
    op = 'SIGNAL_ALIGN'，operands = (func_expr,)

    参数：
        operand         : 被包裹的因子表达式
        signal_freq     : 目标信号频率（如 '1d', '1h'，可以是 $F 参数的值）
        basepoint       : 基准点选择策略 'last'/'first'/callable，默认 'last'
        daily_basepoint : 日倍频时的具体时间基准点，None 则用 basepoint
        end_session_skip: 是否跳过盘间间隔（仅子日频生效），默认 False
        end_session_gap : 盘间间隔阈值，默认 3hours
    """

    def __new__(cls, operand: FactorExpr, *args, **kwargs):
        return super().__new__(cls, 'SIGNAL_ALIGN', operand)

    def __init__(self, operand: FactorExpr, signal_freq: Any,
                 basepoint: 'str|Callable' = 'last',
                 daily_basepoint: 'str|None' = None,
                 end_session_skip: bool = False,
                 end_session_gap: pd.Timedelta = cast(pd.Timedelta, pd.Timedelta('3hours'))):
        super().__init__('SIGNAL_ALIGN', operand)
        self.signal_freq = signal_freq
        self.basepoint = basepoint
        self.daily_basepoint = daily_basepoint
        self.end_session_skip = end_session_skip
        self.end_session_gap = end_session_gap
        # 保存最近一次求值前的原始数据（供 source_table 使用）
        self._raw_data: pd.DataFrame | None = None

    def _structural_extra(self) -> tuple:
        return ('signal_freq', str(self.signal_freq),
                'basepoint', str(self.basepoint),
                'daily_basepoint', str(self.daily_basepoint),
                'end_session_skip', self.end_session_skip,
                'end_session_gap', str(self.end_session_gap))

    def resolve(self, *args, **kwargs) -> FactorExpr:
        resolved: FactorExpr = SignalAlign(
            self.operands[0].resolve(*args, **kwargs),
            self.signal_freq,
            basepoint=self.basepoint,
            daily_basepoint=self.daily_basepoint,
            end_session_skip=self.end_session_skip,
            end_session_gap=self.end_session_gap,
        )
        if self._is_intermediate:
            resolved = resolved.as_intermediate(
                self._intermediate_name,
                factor=kwargs.get('caller', None),
            )
        return resolved

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        data = values[0]
        self._raw_data = data  # 保存未对齐的原始数据
        return signal_align(
            data, self.signal_freq,
            basepoint=self.basepoint,
            daily_basepoint=self.daily_basepoint,
            end_session_skip=self.end_session_skip,
            end_session_gap=cast(pd.Timedelta, self.end_session_gap),
        )

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        data = self.operands[0].evaluate(ctx=ctx)
        signal_names = [
            str(name) for name in data.index.names
            if str(name).startswith('_SIGNAL@')
        ]
        if signal_names:
            if ctx.panel_timeline is None:
                raise ValueError(
                    "outer SignalAlign over a nested signal requires panel_timeline"
                )
            from .pointwise import carry_formed_signal
            template = pd.DataFrame(
                index=ctx.panel_timeline.index,
                columns=data.columns,
            )
            data = carry_formed_signal(data, template)
        return self._apply_op([data])

    # ── 展示 ──

    @property
    def op_name(self) -> str:
        return f'SIGNAL@{self.signal_freq}'

    def _get_alias(self) -> str:
        inner = self.operands[0]._get_alias()
        return f'SIGNAL_{inner}'

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        operand = self.operands[0]
        operand_key = operand._structural_key()
        if subst is not None and operand_key in subst:
            inner = f"{subst[operand_key]}_t"
        else:
            inner = operand._to_latex(subst)
        frequency = str(self.signal_freq if self.signal_freq is not None else '$F')
        frequency = frequency.replace('$', r'\$')
        return (r'\operatorname{Resample}_{\textcolor{red}{' + frequency
                + r'}}\left(' + inner + r'\right)')
