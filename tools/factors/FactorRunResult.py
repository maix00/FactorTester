"""
FactorRunResult — 单个 Factor 在一次计算中的完整结果。

替代 FactorTester 中按 Factor 拆散的 8 个 dict：
  factor_source_tables, factor_tables, factor_returns, factor_return_freqs,
  factor_ic_series, factor_ic_stats, factor_reports（最后一个从未被使用，已废弃）。

所有 per-factor 状态聚合到一个 dataclass，通过 FactorTester.results: Dict[Factor, FactorRunResult] 访问。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import pandas as pd

if TYPE_CHECKING:
    from tools.data.DataFreq import DataFreq
    from tools.factors.Factors import Factor


class FactorRunResult:
    """单个 Factor 在一次运行中产生的所有计算结果。

    所有字段默认为空 DataFrame/None，由下游按需填充：
      - Factors.evaluate() 填入 source_table, table
      - IC test 填入 ic_series, ic_stats，可选填入 returns, table
      - Group test 传入 returns 参数
    """

    __slots__ = (
        "source_table",
        "table",
        "returns",
        "_return_freq",
        "ic_series",
        "ic_stats",
    )

    def __init__(self) -> None:
        self.source_table: pd.DataFrame = pd.DataFrame()
        self.table: pd.DataFrame = pd.DataFrame()
        self.returns: pd.DataFrame = pd.DataFrame()
        self._return_freq: Optional[DataFreq] = None
        self.ic_series: pd.Series = pd.Series(dtype=float)
        self.ic_stats: pd.Series = pd.Series(dtype=float)

    # ── return_freq ──
    @property
    def return_freq(self) -> Optional[DataFreq]:
        return self._return_freq

    @return_freq.setter
    def return_freq(self, value: Optional[DataFreq]) -> None:
        self._return_freq = value

    # ── helpers ──
    def clear_caches(self) -> None:
        """重置可变字段（保留因子身份不变）。"""
        self.source_table = pd.DataFrame()
        self.table = pd.DataFrame()
        self.returns = pd.DataFrame()
        self._return_freq = None
        self.ic_series = pd.Series(dtype=float)
        self.ic_stats = pd.Series(dtype=float)
