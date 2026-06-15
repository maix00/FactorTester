# =============================================================================
# tools/factors/expr/__init__.py
# 因子表达式系统 — 统一导出
# =============================================================================

from .core import FactorExpr, EvaluateContext
from .timeline import PanelTimeline, build_panel_timeline, compact_observed, scatter_observed
from .operands import OperandExpr
from .leaf import ColumnRef, ParamRef, ConstExpr, _to_expr
from .rolling import RollingExpr, RollingOp, _rolling_argmaxmin, _mask_outside_trunc, _resolve_windows
from .shift import ShiftOp, _is_zero_shift_period, _strip_latex_time_subscript
from .cross_sectional import CrossSectionalOp
from .composite import CompositeExpr, _reduce_biop, expr_max, expr_min
from .conditional import WhereOp
from .term_structure import TermStructureOp, term_spread, term_ratio, term_slope
from .signal_align import SignalAlign, signal_align
from .visual_groups import (
    VISUAL_OPERATOR_GROUPS,
    VISUAL_COMPOSITE_KEY,
    VISUAL_OPERATOR_CATEGORY,
    get_visual_operator_groups,
    get_visual_composite_key,
    get_visual_operator_category,
)

# ═════════════════════════════════════════════════════════════════════════════
# 预定义常用列引用（在所有子模块加载后定义，避免循环导入）
# ═════════════════════════════════════════════════════════════════════════════

from tools.data.types.DataColumn import DataColumn

OPEN = ColumnRef(DataColumn.OPEN_ADJUSTED)
HIGH = ColumnRef(DataColumn.HIGH_ADJUSTED)
LOW = ColumnRef(DataColumn.LOW_ADJUSTED)
CLOSE = ColumnRef(DataColumn.CLOSE_ADJUSTED)
VOLUME = ColumnRef(DataColumn.VOLUME)
TURNOVER = ColumnRef(DataColumn.TURNOVER)
OPEN_INTEREST = ColumnRef(DataColumn.OPEN_INTEREST)
VWAP = ColumnRef(DataColumn.VWAP)
SETTLE = ColumnRef(DataColumn.SETTLEMENT_PRICE)

OPEN_RAW = ColumnRef(DataColumn.OPEN)
HIGH_RAW = ColumnRef(DataColumn.HIGH)
LOW_RAW = ColumnRef(DataColumn.LOW)
CLOSE_RAW = ColumnRef(DataColumn.CLOSE)

SMALL_VAL = ConstExpr(1e-10)

__all__ = [
    # core
    "FactorExpr",
    "EvaluateContext",
    "PanelTimeline",
    "build_panel_timeline",
    "compact_observed",
    "scatter_observed",
    # operands
    "OperandExpr",
    # leaf
    "ColumnRef",
    "ParamRef",
    "ConstExpr",
    "_to_expr",
    # rolling
    "RollingExpr",
    "RollingOp",
    "_rolling_argmaxmin",
    "_mask_outside_trunc",
    "_resolve_windows",
    # shift
    "ShiftOp",
    "_is_zero_shift_period",
    "_strip_latex_time_subscript",
    # cross_sectional
    "CrossSectionalOp",
    # composite
    "CompositeExpr",
    "_reduce_biop",
    "expr_max",
    "expr_min",
    # conditional
    "WhereOp",
    # term_structure
    "TermStructureOp",
    "term_spread",
    "term_ratio",
    "term_slope",
    # signal_align
    "SignalAlign",
    "signal_align",
    # visual_groups
    "VISUAL_OPERATOR_GROUPS",
    "VISUAL_COMPOSITE_KEY",
    "VISUAL_OPERATOR_CATEGORY",
    "get_visual_operator_groups",
    "get_visual_composite_key",
    "get_visual_operator_category",
    # pre-defined column references
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "VOLUME",
    "TURNOVER",
    "OPEN_INTEREST",
    "VWAP",
    "SETTLE",
    "OPEN_RAW",
    "HIGH_RAW",
    "LOW_RAW",
    "CLOSE_RAW",
    "SMALL_VAL",
]
