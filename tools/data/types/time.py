# =============================================================================
# tools/data/time.py
# 统一时间点对象
#
# DataTime 封装一个时间点 + 精度 + 可选时区。两个 DataTime 共同定义时间区间。
# 与 DataIndex 配合：DataIndex.slice_by_datatime(start, end) 根据精度自动选层截断。
#
# 时区规则：
#   - precision="trading_day" → 无时区（tz-naive），ts 被 normalize 到 00:00:00
#   - precision="exact" → 可选时区，前端可传入 tz 指定
#
# 用法：
#   start = DataTime.from_dict({"date":"2024-01-01", "time":"09:30", "tz":"Asia/Shanghai"})
#   end   = DataTime.from_dict({"date":"2024-12-31"}, precision="trading_day")
#   mask  = data_index.slice_by_datatime(start, end)
#
# 设计原则：
#   - 一个 DataTime = 一个时间点 + 精度 + 可选时区
#   - 不含任何业务语义（交易/期货等），纯数据结构
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


# ── 时间精度 ──────────────────────────────────────────────────────────────

class TimePrecision:
    """时间精度：trading_day（交易日，忽略时分秒）或 exact（精确）。"""
    TRADING_DAY = "trading_day"
    EXACT = "exact"

    _ALL = frozenset({TRADING_DAY, EXACT})

    @classmethod
    def validate(cls, p: str) -> str:
        if p not in cls._ALL:
            raise ValueError(
                f"TimePrecision: invalid '{p}', expected one of {sorted(cls._ALL)}"
            )
        return p


@dataclass(frozen=True)
class DataTime:
    """统一时间点 — 不可变，前后端通用。

    构造：
        DataTime(ts=pd.Timestamp("2024-01-01 09:30"), tz="Asia/Shanghai")
        DataTime(ts=pd.Timestamp("2024-01-01"), precision="trading_day")  # 交易日，无 tz
        DataTime.from_dict({"date":"2024-01-01", "time":"09:30", "tz":"UTC+8"})
        DataTime.parse("2024-01-01 09:30", tz="Asia/Shanghai")

    属性：
        .ts         : pd.Timestamp | None  时间点
        .tz         : str | None           时区（仅 exact 精度有效；trading_day 精度强制 None）
        .precision  : "trading_day" | "exact"
        .is_set     : bool
    """
    ts: Optional[pd.Timestamp] = None
    precision: str = "exact"
    tz: Optional[str] = None

    def __post_init__(self):
        TimePrecision.validate(self.precision)

        # trading_day 精度：强制无时区 + normalize 到 00:00:00
        if self.precision == TimePrecision.TRADING_DAY:
            if self.tz is not None:
                object.__setattr__(self, 'tz', None)
            if self.ts is not None:
                if self.ts.tzinfo is not None:
                    object.__setattr__(self, 'ts', self.ts.tz_localize(None))
                if self.ts.hour != 0 or self.ts.minute != 0 or self.ts.second != 0:
                    object.__setattr__(self, 'ts', self.ts.normalize())

        # exact 精度：如果传了 tz 且 ts 是 naive，则 localize
        if self.precision == TimePrecision.EXACT and self.tz is not None and self.ts is not None:
            if self.ts.tzinfo is None:
                object.__setattr__(self, 'ts', self.ts.tz_localize(self.tz))

    # ── 工厂 ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict, precision: Optional[str] = None) -> DataTime:
        """从前端 payload 构造。

        data 可选字段：
            date / start_date / end_date → 日期部分 "YYYY-MM-DD"
            time / start_time / end_time → 时间部分 "HH:MM"
            tz                            → 时区（仅 exact 精度有效）
        precision → "trading_day" | "exact"（默认 "exact"）
        """
        date_str = data.get("date") or data.get("start_date") or data.get("end_date")
        time_str = data.get("time") or data.get("start_time") or data.get("end_time")
        tz = data.get("tz") or data.get("timezone") or None
        p = precision or data.get("precision") or data.get("time_precision") or "exact"

        ts = cls._combine(date_str, time_str)
        return cls(ts=ts, precision=p, tz=tz)

    @classmethod
    def parse(cls, value=None, *, precision: str = "exact", tz: Optional[str] = None) -> DataTime:
        """从 str 或 pd.Timestamp 构造。"""
        ts = pd.Timestamp(value) if value else None
        return cls(ts=ts, precision=precision, tz=tz)

    @staticmethod
    def _combine(date_str: Optional[str], time_str: Optional[str]) -> Optional[pd.Timestamp]:
        if not date_str:
            return None
        if time_str:
            return pd.Timestamp(f"{date_str} {time_str}")
        return pd.Timestamp(date_str)

    # ── 谓词 ──────────────────────────────────────────────────────────

    @property
    def is_set(self) -> bool:
        return self.ts is not None

    @property
    def date_str(self) -> Optional[str]:
        """仅日期部分 "YYYY-MM-DD"。"""
        return self.ts.strftime("%Y-%m-%d") if self.ts is not None else None

    @property
    def time_str(self) -> Optional[str]:
        """仅时间部分 "HH:MM"。"""
        return self.ts.strftime("%H:%M") if self.ts is not None else None

    # ── 序列化 ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d: dict = {
            "date": self.date_str,
            "precision": self.precision,
        }
        if self.precision == TimePrecision.EXACT and self.tz:
            d["tz"] = self.tz
        return d

    def __repr__(self) -> str:
        tz_str = f", tz={self.tz}" if self.tz else ""
        return f"DataTime({self.ts}, precision={self.precision}{tz_str})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DataTime):
            return NotImplemented
        return (
            self.ts == other.ts
            and self.precision == other.precision
            and self.tz == other.tz
        )

    def __hash__(self) -> int:
        return hash((self.ts, self.precision, self.tz))
