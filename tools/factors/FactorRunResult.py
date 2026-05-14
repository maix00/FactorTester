"""
FactorRunResult — 单个 Factor 在一次计算中的完整结果。

替代 FactorTester 中按 Factor 拆散的 8 个 dict：
  factor_source_tables, factor_tables, factor_returns, factor_return_freqs,
  factor_ic_series, factor_ic_stats, factor_reports（最后一个从未被使用，已废弃）。

所有 per-factor 状态聚合到一个 slots 类，按测试类别分区，通过 FactorTester.results: Dict[Factor, FactorRunResult] 访问。

与 Factor 三层 expr 的对应关系：
  Factor._expr       = neg(SignalAlign(source_expr, ...)) → table         (对齐+可能有$Rev)
  Factor._func_expr  = neg(source_expr)                   → func_table    (可能有$Rev，无SignalAlign)
  Factor._source_expr = source_expr                       → source_table  (无$Rev，无SignalAlign)

func_table 是 computed property，由 source_table + _factor._func_expr 推导（有 neg 则取反）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import pandas as pd

if TYPE_CHECKING:
    from tools.data.DataFreq import DataFreq
    from tools.factors.Factors import Factor


class FactorRunResult:
    """单个 Factor 在一次运行中产生的所有计算结果，按测试类别分区。

    字段按业务类型分为三组：
      ── Factor.evaluate() 计算层 ──
      source_table : _source_expr.evaluate() — 原始源数据（无 $Rev, 无 SignalAlign）
      table        : _expr.evaluate() = neg(SignalAlign(func_expr,...)) — 对齐+可能有$Rev
      func_table   : _func_expr.evaluate() — 可能有$Rev，无SignalAlign（与 source_table 双向互查)

      ── IC 测试 ──
      ic_series, ic_stats

      ── Group 测试 ──
      returns, _return_freq
    """

    __slots__ = (
        "_factor",
        "_source_table",
        "_func_table",
        "table",
        "_returns",
        "_return_freq",
        "ic_series",
        "ic_stats",
    )

    def __init__(self, factor: Optional[Factor] = None) -> None:
        self._factor: Optional[Factor] = factor
        self._source_table: pd.DataFrame = pd.DataFrame()
        self._func_table: pd.DataFrame = pd.DataFrame()
        self.table: pd.DataFrame = pd.DataFrame()
        self._returns: pd.DataFrame = pd.DataFrame()
        self._return_freq: Optional[DataFreq] = None
        self.ic_series: pd.Series = pd.Series(dtype=float)
        self.ic_stats: pd.Series = pd.Series(dtype=float)

    # ── 内部工具：判断 _func_expr 是否含外层 neg ──

    def _has_neg(self) -> bool:
        if self._factor is None:
            return False
        from tools.factors.FactorExpr import CompositeExpr
        node = self._factor._func_expr
        return isinstance(node, CompositeExpr) and node.op == 'neg'

    # ── source_table / func_table：双向互查，只存有数据的那一个 ──

    @property
    def source_table(self) -> pd.DataFrame:
        """source_table: 无 $Rev 的原始源数据。

        优先返回 _source_table；若为空则从 _func_table 反推（有 neg 则取反，无 neg 则直接用）。
        """
        if not self._source_table.empty:
            return self._source_table
        if self._has_neg():
            return -self._func_table
        return self._func_table

    @source_table.setter
    def source_table(self, value: pd.DataFrame) -> None:
        """写入 source_table（无 $Rev）。同时清空 _func_table（避免冲突）。"""
        if not isinstance(value, pd.DataFrame):
            if isinstance(value, dict):
                value = pd.DataFrame(value)
            else:
                raise TypeError(f"source_table must be pd.DataFrame, got {type(value).__name__}")
        self._source_table = value
        self._func_table = pd.DataFrame()

    @property
    def func_table(self) -> pd.DataFrame:
        """func_table: 可能有 $Rev，无 SignalAlign 的因子值。

        优先返回 _func_table；若为空则从 _source_table 推导（有 neg 则取反）。
        """
        if not self._func_table.empty:
            return self._func_table
        if self._has_neg():
            return -self._source_table
        return self._source_table

    @func_table.setter
    def func_table(self, value: pd.DataFrame) -> None:
        """写入 func_table（可能有 $Rev）。同时清空 _source_table（避免冲突）。"""
        if not isinstance(value, pd.DataFrame):
            if isinstance(value, dict):
                value = pd.DataFrame(value)
            else:
                raise TypeError(f"func_table must be pd.DataFrame, got {type(value).__name__}")
        self._func_table = value
        self._source_table = pd.DataFrame()

    # ── returns ──

    @property
    def returns(self) -> pd.DataFrame:
        return self._returns

    @returns.setter
    def returns(self, value: pd.DataFrame) -> None:
        if not isinstance(value, pd.DataFrame):
            if isinstance(value, dict):
                value = pd.DataFrame(value)
            else:
                raise TypeError(f"returns must be pd.DataFrame, got {type(value).__name__}")
        self._returns = value

    # ── return_freq ──
    @property
    def return_freq(self) -> Optional[DataFreq]:
        return self._return_freq

    @return_freq.setter
    def return_freq(self, value: Optional[DataFreq]) -> None:
        self._return_freq = value

    # ── helpers ──
    def clear_caches(self) -> None:
        """重置可变字段（保留 _factor 不变）。"""
        self._source_table = pd.DataFrame()
        self._func_table = pd.DataFrame()
        self.table = pd.DataFrame()
        self.returns = pd.DataFrame()
        self._return_freq = None
        self.ic_series = pd.Series(dtype=float)
        self.ic_stats = pd.Series(dtype=float)
