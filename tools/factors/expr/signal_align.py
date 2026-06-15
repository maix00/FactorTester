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

from tools.data.DataColumn import DataColumn
from tools.data.DataIndex import finest_index
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.DataProviderProductTS import DataProviderProductTS as DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .composite import CompositeExpr

def signal_align(
    data: pd.DataFrame,
    freq: Any,
    basepoint: 'str|Callable' = 'last',
    daily_basepoint: 'str|None' = None,
    end_session_skip: bool = True,
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

    # 找到 freq 是其整数倍的索引层级（第一个匹配的）
    index_names = [str(n) for n in data.index.names]
    index_freqs = [DataFreq(n) for n in index_names]
    try:
        first_true_idx = next(
            (i for i, f in enumerate(index_freqs)
             if freq_dc.value.total_seconds() % f.value.total_seconds() == 0))
    except StopIteration:
        raise ValueError(
            f"频率 {freq_dc} 不是任何数据索引频率的整数倍")
    multiple = int(freq_dc.value.total_seconds() / index_freqs[first_true_idx].value.total_seconds())

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
        end_session_skip: 是否跳过盘间间隔（仅子日频生效），默认 True
        end_session_gap : 盘间间隔阈值，默认 3hours
    """

    def __new__(cls, operand: FactorExpr, *args, **kwargs):
        return super().__new__(cls, 'SIGNAL_ALIGN', operand)

    def __init__(self, operand: FactorExpr, signal_freq: Any,
                 basepoint: 'str|Callable' = 'last',
                 daily_basepoint: 'str|None' = None,
                 end_session_skip: bool = True,
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
        inner = self.operands[0]._to_latex(subst)
        return f'\\text{{SIGNAL}}_{{{self.signal_freq}}}({inner})'
