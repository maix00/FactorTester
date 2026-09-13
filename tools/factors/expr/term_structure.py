# =============================================================================
# tools/factors/expr/term_structure.py
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
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.providers import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, ColumnRef, ParamRef, _to_expr
from .term_structure_math import (
    DEPTH_TERM_STRUCTURE_OPS,
    PAIR_TERM_STRUCTURE_OPS,
    RANK_TERM_STRUCTURE_OPS,
    evaluate_term_curve,
)

class TermStructureOp(OperandExpr):
    """Futures term-structure snapshot operator.

    This operator evaluates along each product's own futures contract curve at
    every timestamp. It is deliberately separate from CrossSectionalOp: the
    "cross section" here is contracts under one product, not products.
    """

    _LATEX = {
        'term_spread': '\\mathrm{TermSpread}',
        'term_ratio': '\\mathrm{TermRatio}',
        'term_slope': '\\mathrm{TermSlope}',
        'term_log_ratio': '\\mathrm{TermLogRatio}',
        'term_contango': '\\mathrm{TermContango}',
        'term_carry_annualized': '\\mathrm{TermCarryAnn}',
        'term_curvature': '\\mathrm{TermCurvature}',
        'term_slope_segment': '\\mathrm{TermSlopeSeg}',
        'term_rank_value': '\\mathrm{TermRankValue}',
    }
    _PAIR_OPS = PAIR_TERM_STRUCTURE_OPS
    _DEPTH_OPS = DEPTH_TERM_STRUCTURE_OPS
    _RANK_OPS = RANK_TERM_STRUCTURE_OPS

    def __init__(self, op: str, *operands: FactorExpr):
        if op not in self._LATEX:
            raise ValueError(f"Unknown term structure op: {op}")
        expected = 3 if op in self._PAIR_OPS else 2
        if len(operands) != expected:
            raise ValueError(f"{op} requires {expected} operands, got {len(operands)}")
        super().__init__(op, *operands)

    def _structural_key(self) -> tuple:
        return (type(self).__name__, self.op, tuple(op._structural_key() for op in self.operands))

    def supports_incremental(self) -> bool:
        try:
            self._term_param_values()
        except Exception:
            return False
        return True

    def _time_index_for_product(
        self,
        product: 'Product',
        freq: DataFreq,
        preloaded: Optional[Dict[Any, pd.DataFrame]] = None,
    ) -> pd.Index:
        if preloaded is not None:
            data = preloaded.get((product, freq.name))
            if data is not None:
                return data.index
        try:
            data = product.get_some_data(freq, copy=False)
        except Exception:
            return pd.Index([])
        if data is None or data.empty:
            return pd.Index([])
        return data.index

    @staticmethod
    def _trading_days_for_index(idx: pd.Index) -> pd.DatetimeIndex:
        if isinstance(idx, pd.MultiIndex):
            level_pos = 0
            for i, name in enumerate(idx.names):
                if name and str(name).upper().startswith('DAY'):
                    level_pos = i
                    break
            ts = pd.to_datetime(idx.get_level_values(level_pos))
        else:
            ts = pd.to_datetime(idx)
        days = pd.DatetimeIndex(ts)
        if days.tz is not None:
            days = days.tz_localize(None)
        return getattr(days, 'normalize')()

    @staticmethod
    def _const_operand_value(expr: FactorExpr) -> Any:
        if isinstance(expr, ConstExpr):
            return expr.value
        raise TypeError(f"TermStructureOp operands must resolve to ConstExpr, got {type(expr).__name__}")

    @staticmethod
    def _column_name(expr: FactorExpr) -> str:
        if isinstance(expr, ColumnRef):
            return TermStructureOp._term_structure_column_name(expr.column)
        if isinstance(expr, ConstExpr):
            return TermStructureOp._term_structure_column_name(DataColumn(expr.value))
        raise TypeError(f"TermStructureOp column operand must resolve to ConstExpr or ColumnRef, got {type(expr).__name__}")

    @staticmethod
    def _term_structure_column_name(column: DataColumn) -> str:
        adjusted_to_raw = {
            DataColumn.OPEN_ADJUSTED: DataColumn.OPEN,
            DataColumn.HIGH_ADJUSTED: DataColumn.HIGH,
            DataColumn.LOW_ADJUSTED: DataColumn.LOW,
            DataColumn.CLOSE_ADJUSTED: DataColumn.CLOSE,
        }
        return adjusted_to_raw.get(column, column).name

    @staticmethod
    def _operand_latex_arg(expr: FactorExpr, *, column: bool = False) -> str:
        if column:
            if isinstance(expr, ColumnRef):
                return expr.column.name
            if isinstance(expr, ConstExpr):
                return DataColumn(expr.value).name
            if isinstance(expr, ParamRef):
                return expr._parameter_latex()
        if isinstance(expr, ConstExpr):
            return str(expr.value)
        return expr._to_latex()

    @staticmethod
    def _operand_alias_arg(expr: FactorExpr, *, column: bool = False) -> str:
        if column:
            if isinstance(expr, ColumnRef):
                return expr.column.value
            if isinstance(expr, ConstExpr):
                return DataColumn(expr.value).value
        return expr._get_alias()

    def _term_param_values(self) -> tuple[int, int, int, str]:
        if self.op in self._PAIR_OPS:
            near_rank = int(self._const_operand_value(self.operands[0]))
            far_rank = int(self._const_operand_value(self.operands[1]))
            column = self._column_name(self.operands[2])
            return near_rank, far_rank, 0, column
        if self.op in self._RANK_OPS:
            rank = int(self._const_operand_value(self.operands[0]))
            column = self._column_name(self.operands[1])
            return rank, 0, 0, column
        depth = int(self._const_operand_value(self.operands[0]))
        column = self._column_name(self.operands[1])
        return 0, 1, depth, column

    def _evaluate_curve(self, curve: pd.DataFrame, near_rank: int, far_rank: int, depth: int, column: str) -> float:
        return evaluate_term_curve(
            self.op,
            curve,
            near_rank=near_rank,
            far_rank=far_rank,
            depth=depth,
            column=column,
        )

    def _evaluate_series_from_curves(
        self,
        product: 'Product',
        trading_days: pd.DatetimeIndex,
        near_rank: int,
        far_rank: int,
        depth: int,
        column: str,
    ) -> pd.Series:
        curve_depth = max(near_rank, far_rank, depth) + 1
        batch_fn = getattr(product, 'get_term_structures', None)
        if callable(batch_fn):
            curves = batch_fn(trading_days, depth=curve_depth)
            if not isinstance(curves, dict):
                raise TypeError(
                    f"Product {getattr(product, 'name', product)} "
                    "get_term_structures must return a dict"
                )
            values = [
                self._evaluate_curve(
                    curves.get(pd.Timestamp(day).normalize(), pd.DataFrame()),
                    near_rank,
                    far_rank,
                    depth,
                    column,
                )
                for day in trading_days
            ]
            return pd.Series(values, index=trading_days, dtype=float)
        values = []
        for day in trading_days:
            curve = product.get_term_structure(day, depth=curve_depth)
            values.append(self._evaluate_curve(curve, near_rank, far_rank, depth, column))
        return pd.Series(values, index=trading_days, dtype=float)

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        near_rank, far_rank, depth, column = self._term_param_values()
        products = ctx.products
        freq = ctx.freq
        series_dict = {}
        for product in products:
            supports_term_structure = getattr(product, 'supports_term_structure', None)
            if callable(supports_term_structure) and not supports_term_structure():
                continue
            if not hasattr(product, 'get_term_structure'):
                continue
            raw_idx = self._time_index_for_product(
                product,
                freq,
                ctx.preloaded,
            )
            if len(raw_idx) == 0:
                continue
            trading_days = self._trading_days_for_index(raw_idx)
            if len(trading_days) == 0:
                continue
            unique_days = trading_days.drop_duplicates()
            if self.op == 'term_spread':
                batch_fn = getattr(product, 'term_spread_series', None)
                if not callable(batch_fn):
                    raise TypeError(f"Product {getattr(product, 'name', product)} missing required method term_spread_series")
                series = batch_fn(unique_days, near_rank=near_rank, far_rank=far_rank, column=column)
            elif self.op == 'term_ratio':
                batch_fn = getattr(product, 'term_ratio_series', None)
                if not callable(batch_fn):
                    raise TypeError(f"Product {getattr(product, 'name', product)} missing required method term_ratio_series")
                series = batch_fn(unique_days, near_rank=near_rank, far_rank=far_rank, column=column)
            else:
                if self.op == 'term_slope':
                    batch_fn = getattr(product, 'term_slope_series', None)
                    if callable(batch_fn):
                        series = batch_fn(unique_days, depth=depth, column=column)
                    else:
                        series = self._evaluate_series_from_curves(product, unique_days, near_rank, far_rank, depth, column)
                else:
                    series = self._evaluate_series_from_curves(product, unique_days, near_rank, far_rank, depth, column)
            if not isinstance(series, pd.Series):
                raise TypeError(f"Batch method for {getattr(product, 'name', product)} must return pd.Series, got {type(series).__name__}")
            mapped = series.astype(float).reindex(trading_days).to_numpy(dtype=float)
            series_dict[product] = pd.Series(mapped, index=raw_idx, dtype=float)
        if not series_dict:
            return pd.DataFrame()
        result = pd.concat(series_dict, axis=1)
        result.columns = list(series_dict.keys())
        return result

    @property
    def op_name(self) -> str:
        return self.op

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        if self.op in self._PAIR_OPS:
            near_rank = self._operand_latex_arg(self.operands[0])
            far_rank = self._operand_latex_arg(self.operands[1])
            column = self._operand_latex_arg(self.operands[2], column=True)
            return f"{self._LATEX[self.op]}_{{{near_rank},{far_rank}}}({column})"
        depth = self._operand_latex_arg(self.operands[0])
        column = self._operand_latex_arg(self.operands[1], column=True)
        return f"{self._LATEX[self.op]}_{{{depth}}}({column})"

    def _get_alias(self) -> str:
        if self.op in self._PAIR_OPS:
            near_rank = self._operand_alias_arg(self.operands[0])
            far_rank = self._operand_alias_arg(self.operands[1])
            column = self._operand_alias_arg(self.operands[2], column=True)
            return f"{self.op}_{column}_{near_rank}_{far_rank}"
        depth = self._operand_alias_arg(self.operands[0])
        column = self._operand_alias_arg(self.operands[1], column=True)
        return f"{self.op}_{column}_{depth}"


def term_spread(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Near-far futures term-structure spread: near - far."""
    return TermStructureOp('term_spread', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_ratio(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Near-far futures term-structure ratio: near / far - 1."""
    return TermStructureOp('term_ratio', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_slope(depth: Any = 4, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Linear slope of futures prices against days-to-maturity."""
    return TermStructureOp('term_slope', _to_expr(depth), _to_expr(column))


def term_log_ratio(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Log near-far ratio: log(near / far)."""
    return TermStructureOp('term_log_ratio', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_contango(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Contango strength: far / near - 1."""
    return TermStructureOp('term_contango', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_carry_annualized(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Annualized backwardation/carry: (near / far - 1) * 365 / days_between."""
    return TermStructureOp('term_carry_annualized', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_curvature(depth: Any = 4, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Quadratic curvature coefficient of futures prices against days-to-maturity."""
    return TermStructureOp('term_curvature', _to_expr(depth), _to_expr(column))


def term_slope_segment(near_rank: Any = 0, far_rank: Any = 1, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Two-rank segment slope: (far - near) / (far_days - near_days)."""
    return TermStructureOp('term_slope_segment', _to_expr(near_rank), _to_expr(far_rank), _to_expr(column))


def term_rank_value(rank: Any = 0, column: Any = DataColumn.CLOSE) -> TermStructureOp:
    """Value of the rank-th contract on the product's futures curve."""
    return TermStructureOp('term_rank_value', _to_expr(rank), _to_expr(column))


# ═════════════════════════════════════════════════════════════════════════════
# 预定义常用列引用（方便直接使用）
# ═════════════════════════════════════════════════════════════════════════════

OPEN = ColumnRef(DataColumn.OPEN_ADJUSTED)
HIGH = ColumnRef(DataColumn.HIGH_ADJUSTED)
LOW = ColumnRef(DataColumn.LOW_ADJUSTED)
CLOSE = ColumnRef(DataColumn.CLOSE_ADJUSTED)
VOLUME = ColumnRef(DataColumn.VOLUME)
TURNOVER = ColumnRef(DataColumn.TURNOVER)
OPEN_INTEREST = ColumnRef(DataColumn.OPEN_INTEREST)
VWAP = ColumnRef(DataColumn.VWAP)
SETTLE = ColumnRef(DataColumn.SETTLEMENT_PRICE)

# 原始（不复权）价格列
OPEN_RAW = ColumnRef(DataColumn.OPEN)
HIGH_RAW = ColumnRef(DataColumn.HIGH)
LOW_RAW = ColumnRef(DataColumn.LOW)
CLOSE_RAW = ColumnRef(DataColumn.CLOSE)

SMALL_VAL = ConstExpr(1e-10)


# ═════════════════════════════════════════════════════════════════════════════
# 信号对齐工具函数 & 表达式节点
# ═════════════════════════════════════════════════════════════════════════════
