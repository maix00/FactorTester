# =============================================================================
# tools/data/time_index.py
# 时间索引管理器
#
# DataIndex 封装 DatetimeIndex / MultiIndex（两列 DatetimeIndex，均以 _SIGNAL@ 命名）
# 的时间层提取、时区对齐、精度转换、频率检测、时间截断等操作。
# 它是 DataFreq/DataColumn/ProductDataView 的同级数据层基础类型。
#
# MultiIndex 场景：如 _SIGNAL@DAY1 + _SIGNAL@MIN5，表示同一组数据在不同时间精度下的索引。
# DataIndex 通过 signal_index 属性自动选出合适的层。
#
# 设计原则：
#   - DataIndex(index) 构造，自动识别 index 类型并提取信号时间层
#   - .tz_align(ts) / .tz_normalize() 处理 tz-aware ↔ tz-naive 对齐
#   - .to_trading_days() 将任意精度 index 降采样到天级
#   - .slice_by(start, end) 按时间戳切片
#   - .freq 属性检测索引频率
# =============================================================================
from __future__ import annotations

from typing import Any, Optional, Sequence, cast

import numpy as np
import pandas as pd


# ── MultiIndex _SIGNAL@ 命名约定 ──────────────────────────────────────────
_SIGNAL_PREFIX = "_SIGNAL@"

# 不会产生日内分辨率的频率名前缀（用于 exact 守卫和 day 精度层级选择）
# DataFreq 不支持 WEEK/MONTH 等，这里用手工前缀匹配作为回退
_DAY_LEVEL_PREFIXES = ('DAY', 'WEEK', 'MONTH', 'YEAR')


def _is_day_level_name(name: str) -> bool:
    """判断层级名是否表示天倍数级别（如 _SIGNAL@DAY1 / _SIGNAL@WEEK1）。"""
    from .time_freq import DataFreq

    name_upper = str(name).upper()
    if name_upper in {"TRADING_DAY", "TRADE_DAY"} or name_upper.endswith("_TRADING_DAY"):
        return True
    freq_str = name.split(_SIGNAL_PREFIX, 1)[-1] if _SIGNAL_PREFIX in name else name
    try:
        return DataFreq(freq_str).is_day_multiple()
    except Exception:
        freq_upper = freq_str.upper()
        return freq_upper.startswith(_DAY_LEVEL_PREFIXES) or freq_upper in {"TRADING_DAY", "TRADE_DAY"}


def _last_in_groups(values: pd.DatetimeIndex) -> np.ndarray:
    values = pd.DatetimeIndex(values)
    mask: np.ndarray = np.zeros(len(values), dtype=bool)
    if len(values) == 0:
        return mask
    if len(values) == 1:
        mask[0] = True
        return mask
    normalized = DataIndex.normalized_days(values)
    day_change = np.flatnonzero(normalized[1:].to_numpy() != normalized[:-1].to_numpy()) + 1
    boundaries = np.concatenate([day_change, np.array([len(values)], dtype=int)])
    for end in boundaries:
        mask[end - 1] = True
    return mask


def _has_subday_component(values: pd.DatetimeIndex) -> bool:
    values = pd.DatetimeIndex(values)
    if len(values) == 0:
        return False
    naive = values.tz_localize(None) if values.tz is not None else values
    return bool((naive != DataIndex.normalized_days(naive)).any())


class DataIndex:
    """时间索引管理器 — 封装 DatetimeIndex / MultiIndex（纯时间层）的操作。

    构造：
        DataIndex(index)  — 从 pd.Index / DatetimeIndex / MultiIndex 构造

    核心属性：
        .raw          : 原始传入的 pd.Index
        .signal_index : 提取后的 DatetimeIndex（纯时间层）
        .tz           : 时区信息
        .freq          : 推断的 DataFreq

    常用方法：
        .tz_align(ts)          — 将 Timestamp 的 tz 对齐到 signal_index
        .to_trading_days()     — 降采样到天级 DatetimeIndex（去 tz + normalize）
        .slice_by(start, end)  — 按时间区间截取 boolean mask
        .slice_index_by(start, end) — 按时间区间截取返回新 DataIndex
        .intersection(other)   — 交集
        .union(other)          — 并集
        .where(mask)           — 按 boolean mask 子集
    """

    __slots__ = ("raw", "_signal_cache", "_time_pref")
    raw: pd.Index
    _signal_cache: Optional[pd.DatetimeIndex]
    _time_pref: Any

    def __init__(
        self,
        index: pd.Index | DataIndex,
        *,
        time_level: Optional[int] = None,
        time_name: Optional[str] = None,
    ) -> None:
        """构造 DataIndex。

        Parameters
        ----------
        index : pd.Index | DataIndex
            原始索引或另一个 DataIndex。
        time_level : int, optional
            对于 MultiIndex，指定用第几层（0-based）作为信号时间层。
            仅当 index 是 MultiIndex 时生效；DatetimeIndex 上被忽略。
        time_name : str, optional
            对于 MultiIndex，指定匹配层级名称作为信号时间层。
            优先级高于 time_level 和 _SIGNAL@ 前缀的自动匹配。
        """
        if isinstance(index, DataIndex):
            raw: pd.Index = index.raw
            signal_cache: Optional[pd.DatetimeIndex] = index._signal_cache
            time_pref: Any = index._time_pref
        else:
            raw = index
            signal_cache = None
            time_pref = None
            if isinstance(index, pd.MultiIndex):
                # 守卫：不允许 MultiIndex 中出现多个 _SIGNAL@ 层级
                signal_names = [n for n in index.names if n and str(n).startswith(_SIGNAL_PREFIX)]
                if len(signal_names) > 1:
                    raise ValueError(
                        f"DataIndex: MultiIndex must have at most one _SIGNAL@ level, "
                        f"got {len(signal_names)}: {signal_names}"
                    )
                if time_name is not None:
                    if time_name not in index.names:
                        raise ValueError(
                            f"DataIndex: time_name='{time_name}' not found in "
                            f"MultiIndex names {list(index.names)}"
                        )
                    time_pref = time_name  # 存 str，用于 _resolve_signal_level 优先匹配
                elif time_level is not None:
                    nlevels = index.nlevels
                    if time_level < 0 or time_level >= nlevels:
                        raise ValueError(
                            f"DataIndex: time_level={time_level} out of range "
                            f"for MultiIndex with {nlevels} levels"
                        )
                    time_pref = time_level
        self.raw = raw
        self._signal_cache = signal_cache
        self._time_pref = time_pref

    # ── 信号时间提取 ──────────────────────────────────────────────────────

    @property
    def signal_index(self) -> pd.DatetimeIndex:
        """提取纯信号时间层 DatetimeIndex。

        优先级（MultiIndex 时）：
        1. _SIGNAL@ 前缀匹配的层级（自动）
        2. time_name 参数指定的层级
        3. time_level 参数指定的层级（0-based）
        4. 最后一层（默认回退）

        DatetimeIndex 直接转换返回。
        """
        if self._signal_cache is not None:
            return self._signal_cache
        idx = self.raw
        if isinstance(idx, pd.MultiIndex):
            result = self._resolve_signal_level(idx)
        else:
            result = pd.DatetimeIndex(idx)
        self._signal_cache = result
        return result

    def _resolve_signal_level(self, idx: pd.MultiIndex) -> pd.DatetimeIndex:
        """按优先级解析 MultiIndex 的信号时间层。

        优先级：
        0. _time_pref (str) → 精确名称匹配
        1. _time_pref (int) → time_level 按位置（0-based）
        2. _SIGNAL@ 前缀自动匹配
        3. 最后一层（默认回退）
        """
        pref = self._time_pref
        signal_name: Optional[str] = None

        # 0) time_name 明确指定 → 精确按名匹配
        if isinstance(pref, str):
            if pref in idx.names:
                signal_name = pref
            else:
                raise KeyError(
                    f"DataIndex: time_name '{pref}' not found in MultiIndex levels "
                    f"{list(idx.names)}"
                )
        elif isinstance(pref, int):
            # 用户明确指定 level → 直接用
            return pd.DatetimeIndex(idx.get_level_values(pref), name=idx.names[pref])
        else:
            # 2) _SIGNAL@ 前缀自动匹配
            found = next(
                (n for n in idx.names if n and str(n).startswith(_SIGNAL_PREFIX)),
                None,
            )
            signal_name = str(found) if found is not None else None

        if signal_name is not None:
            level = idx.names.index(signal_name)
        else:
            # 3) fallback 最后一层
            level = -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])

    @property
    def signal_name(self) -> Optional[str]:
        """信号时间层的层级名称（MultiIndex 时有意义）。"""
        return str(self.signal_index.name) if self.signal_index.name is not None else None

    @property
    def is_multi(self) -> bool:
        """是否为 MultiIndex。"""
        return isinstance(self.raw, pd.MultiIndex)

    @property
    def is_datetime(self) -> bool:
        """原始索引是否为纯 DatetimeIndex。"""
        return isinstance(self.raw, pd.DatetimeIndex)

    @property
    def finest_index(self) -> pd.DatetimeIndex:
        """始终返回最精细的时间列作为 DatetimeIndex。

        与 signal_index 不同：finest_index 始终取最后一层 (get_level_values(-1))，
        不遵循 _SIGNAL@ 前缀匹配优先级。
        用于需要逐 bar 精度（格式化输出、逐点截断、day_periods 计算等）。
        """
        idx = self.raw
        if isinstance(idx, pd.MultiIndex):
            result = pd.DatetimeIndex(idx.get_level_values(-1))
            return result
        return pd.DatetimeIndex(idx)

    def event_timestamps(self) -> pd.DatetimeIndex:
        """返回用于逐 bar / 事件驱动查询的实际事件时间层。

        这是 ``signal_index`` 的语义化别名。调用方不应再自行猜测
        ``MIN1``/``trade_time``/最后一层；统一交给 DataIndex 解析。
        """
        return self.signal_index

    def trading_day_index(self) -> pd.DatetimeIndex:
        """返回交易日层。

        MultiIndex 中优先使用 DAY1 / trading_day / trade_day 等日级层；
        普通 DatetimeIndex 或没有显式交易日层时，退化为事件时间的自然日。
        """
        idx = self.raw
        if isinstance(idx, pd.MultiIndex):
            day_level = next(
                (i for i, name in enumerate(idx.names) if name and _is_day_level_name(str(name))),
                None,
            )
            if day_level is not None:
                return DataIndex.normalized_days(idx.get_level_values(day_level))
        return DataIndex.normalized_days(self.event_timestamps())

    @staticmethod
    def event_timestamps_from_index(index: pd.Index | DataIndex) -> pd.DatetimeIndex:
        return index.event_timestamps() if isinstance(index, DataIndex) else DataIndex(index).event_timestamps()

    @staticmethod
    def trading_day_index_from_index(index: pd.Index | DataIndex) -> pd.DatetimeIndex:
        return index.trading_day_index() if isinstance(index, DataIndex) else DataIndex(index).trading_day_index()

    @staticmethod
    def normalized_days(values: Any) -> pd.DatetimeIndex:
        """从原始列值构造标准化的日级别 DatetimeIndex（去tz + normalize）。

        等价于 pd.DatetimeIndex(pd.to_datetime(values)).tz_localize(None).normalize()，
        零构造开销（无 DataIndex 实例）。
        """
        result = pd.DatetimeIndex(pd.to_datetime(values))
        if result.tz is not None:
            result = pd.DatetimeIndex(result.tz_localize(None))
        return pd.DatetimeIndex(result.to_numpy(dtype="datetime64[D]"))

    # ── 时区 ──────────────────────────────────────────────────────────────

    @property
    def tz(self) -> Any:
        """信号索引的时区。"""
        return self.signal_index.tz

    def tz_align(self, ts: Any) -> pd.Timestamp:
        """将任意 Timestamp 的时区对齐到 signal_index，避免 tz-aware/naive 比较错误。"""
        ts = pd.Timestamp(ts)
        idx_tz = self.signal_index.tz
        if idx_tz is None:
            return ts.tz_localize(None) if ts.tzinfo is not None else ts
        if ts.tzinfo is None:
            return ts.tz_localize(idx_tz)
        return ts.tz_convert(idx_tz)

    # ── 按信号时间层定位行 ──────────────────────────────────────────────────

    @property
    def level_for_xs(self) -> Any:
        """用于 ``DataFrame.xs(..., level=...)`` 的层级标识。

        MultiIndex 时返回 signal_index 对应的层级名（解析失败则回退到位置
        -1，与 signal_index 自身的回退一致）；非 MultiIndex 时无意义，
        返回 None（调用方应直接用 .loc，不走 xs）。
        """
        if not self.is_multi:
            return None
        idx = cast(pd.MultiIndex, self.raw)
        name = self.signal_name
        return name if name in idx.names else -1

    def contains(self, ts: Any) -> bool:
        """`ts`（自动 tz 对齐）是否命中 signal_index 中的某个时间点。"""
        return self.tz_align(ts) in self.signal_index

    def asof_value(self, ts: Any) -> pd.Timestamp:
        """signal_index 中 <= `ts`（自动 tz 对齐）的最近一个时间点。

        用于先定位、再用 `.xs(value, level=level_for_xs)` 取行 —— 同时支持
        精确命中和 as-of 回退（结算时段缺口、调度时间没有精确落在某根 bar
        上等场景）。命中或之前都没有数据时抛 KeyError。
        """
        aligned = self.tz_align(ts)
        sig = self.signal_index
        if aligned in sig:
            return aligned
        # Pandas may keep DatetimeIndex values in microsecond resolution on
        # newer runtimes; strategy scheduling can deliberately add 1ns to
        # distinguish bar-close signal time from order action time.  Compare
        # in nanosecond integers so as-of lookup does not ask pandas to cast a
        # nanosecond Timestamp losslessly into a microsecond index.
        sig_ns: np.ndarray = sig.to_numpy(dtype="datetime64[ns]").astype("int64", copy=False)
        pos = int(np.searchsorted(sig_ns, aligned.value, side="right") - 1)
        if pos < 0:
            raise KeyError(f"no signal_index value at or before {aligned!r}")
        return cast(pd.Timestamp, sig[pos])

    # ── 频率 ──────────────────────────────────────────────────────────────

    @property
    def freq(self) -> Any:
        """根据信号时间层的名称推断 DataFreq。

        时机：信号层名如 '_SIGNAL@MIN5' → DataFreq('MIN5')
              否则从实际时间戳间隔推断。
        """
        from .time_freq import DataFreq

        sig_name = self.signal_name
        if sig_name and _SIGNAL_PREFIX in sig_name:
            freq_str = sig_name.split(_SIGNAL_PREFIX, 1)[-1]
            try:
                return DataFreq(freq_str)
            except Exception:
                pass
        # 从信号索引推断——取众数间隔
        if len(self.signal_index) >= 2:
            diffs = self.signal_index[1:] - self.signal_index[:-1]
            if len(diffs) == 0:
                return None
            # pandas 3.x TimedeltaIndex 无 mode()，用 value_counts
            vc = diffs.value_counts()
            mode_diff = cast(pd.Timedelta, vc.index[0])
            if mode_diff > pd.Timedelta(0):
                return DataFreq(mode_diff)
        return None

    # ── 精度转换 ──────────────────────────────────────────────────────────

    def to_trading_days(self) -> pd.DatetimeIndex:
        """将 signal_index 转换为天级 DatetimeIndex（去 tz + normalize）。

        用于与 roller_info（日级别）做区间匹配等场景。
        分钟级索引会被 normalize 到 00:00:00。
        """
        result = self.signal_index
        if result.tz is not None:
            result = pd.DatetimeIndex(result.tz_localize(None))
        return DataIndex.normalized_days(result)

    def end_of_trading_day(self) -> np.ndarray:
        """标记每个交易日最后一个 bar。

        优先使用 raw MultiIndex 里的交易日层（通常是 DAY1 / trading_day）。
        如果拿不到交易日层，再退回到时间戳按日归组。
        """
        idx = self.raw
        if isinstance(idx, pd.MultiIndex):
            day_level = next(
                (i for i, name in enumerate(idx.names) if name and _is_day_level_name(str(name))),
                None,
            )
            if day_level is not None:
                trading_days = pd.DatetimeIndex(idx.get_level_values(day_level))
                return _last_in_groups(trading_days)
        ts = self.finest_index
        if len(ts) == 0:
            return np.zeros(0, dtype=bool)
        return _last_in_groups(DataIndex.normalized_days(ts))

    def trading_day_last_event_times(self) -> pd.Series:
        """返回每个交易日对应的最后一个最细粒度事件时间。

        交易日层通常只有日期信息且不带时区；它只能作为分组键。真正
        注册事件时必须使用该交易日分组内最后一条 ``finest_index``
        时间戳，这个时间戳保留原始时区。典型例子：夜盘时间
        ``2026-03-09 21:00 Asia/Shanghai`` 属于 ``2026-03-10`` 交易日，
        但交易日结算通知应注册在 ``2026-03-10`` 交易日最后一条
        trade_time 之后，而不是把无时区交易日日期当成事件时间。
        """
        event_times = self.finest_index
        trading_days = self.trading_day_index()
        if len(event_times) == 0:
            return pd.Series(dtype="datetime64[ns]")
        mask = _last_in_groups(trading_days)
        return pd.Series(
            event_times[mask],
            index=pd.DatetimeIndex(trading_days[mask]),
            name="event_time",
        )

    @staticmethod
    def trading_day_last_event_times_from_index(index: pd.Index | DataIndex) -> pd.Series:
        return (
            index.trading_day_last_event_times()
            if isinstance(index, DataIndex)
            else DataIndex(index).trading_day_last_event_times()
        )

    # ── 时间切片 ──────────────────────────────────────────────────────────

    def slice_by(self, start: Any = None, end: Any = None) -> np.ndarray:
        """返回 boolean mask (np.ndarray)，标记 signal_index 在 [start, end] 范围内的行。

        start/end 可以是任意 Timestamp-like，会自动做 tz 对齐。
        """
        mask: np.ndarray = np.ones(len(self.signal_index), dtype=bool)
        if start is not None:
            s = self.tz_align(start)
            mask &= self.signal_index >= s
        if end is not None:
            e = self.tz_align(end)
            mask &= self.signal_index <= e
        return mask

    def slice_index_by(self, start: Any = None, end: Any = None) -> DataIndex:
        """按时间区间截取，返回新 DataIndex。"""
        mask = self.slice_by(start, end)
        return self.where(mask)

    def slice_by_datatime(self, start_dt, end_dt) -> np.ndarray:
        """根据两个 DataTime 对象截取 boolean mask。

        start_dt, end_dt : DataTime（单时间点 + 精度 + 可选时区）
        - 若任一 precision == "trading_day"，用交易日层截断（end 自动推至当天结束）
        - 否则用当前 signal_index 精确截断
        - DataTime.ts 的时区由 DataTime 保证（exact + tz → tz-aware；trading_day → tz-naive）
          此处通过 slice_by() → tz_align() 自动对齐

        守卫：
        - exact 精度要求 signal_index 频率 < 1day（日内），否则天级索引无法做日内截断
        """
        from .time import DataTime  # noqa: F811

        if not isinstance(start_dt, DataTime) or not isinstance(end_dt, DataTime):
            raise TypeError("slice_by_datatime expects two DataTime objects")
        if not start_dt.is_set or not end_dt.is_set:
            raise ValueError("Both DataTime must have ts set")

        # 精度：任一是 trading_day 就用交易日层
        precision = "trading_day" if (
            start_dt.precision == "trading_day" or end_dt.precision == "trading_day"
        ) else "exact"

        if precision == "trading_day":
            di_for_slice = self
            if self.is_multi:
                from .time_freq import DataFreq
                day_name = next(
                    (n for n in self.raw.names
                     if n and _is_day_level_name(str(n))),
                    None,
                )
                if day_name is not None:
                    di_for_slice = DataIndex(self.raw, time_name=str(day_name))
            # trading_day 精度：end 代表当天结束，推后一天使 <= 变为包含整天
            end_ts = cast(pd.Timestamp, end_dt.ts) + pd.Timedelta(days=1)
            return di_for_slice.slice_by(start_dt.ts, end_ts)
        else:
            # 守卫：exact 精度要求信号索引有日内分量。显式日级信号层拒绝；
            # 对普通 DatetimeIndex，不能只按相邻间隔判断，因为每天 09:00
            # 一根的序列间隔也是 DAY1，但语义仍是 exact 时间点。
            sig_freq = self.freq
            explicit_day_level = bool(
                self.signal_name
                and _SIGNAL_PREFIX in str(self.signal_name)
                and _is_day_level_name(str(self.signal_name))
            )
            inferred_day_without_subday = (
                not self.signal_name
                and sig_freq is not None
                and sig_freq.is_day_multiple()
                and not _has_subday_component(self.signal_index)
            )
            if explicit_day_level or inferred_day_without_subday:
                raise ValueError(
                    f"slice_by_datatime: exact precision requires intraday signal_index, "
                    f"but signal_name='{self.signal_name}' has freq={sig_freq} "
                    f"which is a day-multiple (>= 1day, no sub-day component). "
                    f"Use precision='trading_day' or provide an intraday DataIndex."
                )
            return self.slice_by(start_dt.ts, end_dt.ts)

    def where(self, mask: pd.Index | np.ndarray) -> DataIndex:
        """按 boolean mask 取子集。"""
        if isinstance(mask, pd.Index):
            raw_mask = np.asarray(mask, dtype=bool)
        else:
            raw_mask = np.asarray(mask, dtype=bool)
        return DataIndex(self.raw[raw_mask])

    # ── 集合操作 ──────────────────────────────────────────────────────────

    def intersection(self, other: DataIndex | pd.Index) -> DataIndex:
        """与另一个 DataIndex 取信号时间交集。"""
        other_signal = other.signal_index if isinstance(other, DataIndex) else pd.DatetimeIndex(other)
        return DataIndex(
            self.signal_index.intersection(other_signal)
        )

    def union(self, other: DataIndex | pd.Index) -> DataIndex:
        """与另一个 DataIndex 取信号时间并集（跨时区安全，输出 UTC）。"""
        other_signal = other.signal_index if isinstance(other, DataIndex) else pd.DatetimeIndex(other)

        def _to_utc_series(di: pd.DatetimeIndex):
            utc_vals = [
                pd.Timestamp(v).tz_localize('UTC') if pd.Timestamp(v).tzinfo is None
                else pd.Timestamp(v).tz_convert('UTC')
                for v in di
            ]
            return utc_vals

        merged_utc = sorted(set(_to_utc_series(self.signal_index)) | set(_to_utc_series(other_signal)))
        return DataIndex(pd.DatetimeIndex(merged_utc))

    def to_date_range(self, freq: Any) -> pd.DatetimeIndex:
        """从 signal_index 的首尾生成 date_range（用于构建 calendar_index）。"""
        if len(self.signal_index) == 0:
            return pd.DatetimeIndex([])
        from .time_freq import DataFreq
        freq_obj = DataFreq(freq)
        return pd.date_range(
            start=self.signal_index[0],
            end=self.signal_index[-1],
            freq=freq_obj.value,
        )

    # ── 便捷方法 ──────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.raw)

    def __repr__(self) -> str:
        return f"DataIndex(len={len(self)}, tz={self.tz}, signal_name={self.signal_name})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DataIndex):
            return self.raw.equals(other.raw)
        if isinstance(other, pd.Index):
            return self.raw.equals(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(id(self))


def finest_index(index: pd.Index) -> pd.DatetimeIndex:
    """取索引的最精细时间列 — 始终返回最后一层 DatetimeIndex，零构造开销。

    调用方无需构造 DataIndex 实例：
        ts = finest_index(df.index)

    与 MultiIndex 中的 _SIGNAL@ 命名约定无关；
    仅取最后一层 (get_level_values(-1))。
    """
    if isinstance(index, pd.MultiIndex):
        return pd.DatetimeIndex(index.get_level_values(-1))
    return pd.DatetimeIndex(index)
