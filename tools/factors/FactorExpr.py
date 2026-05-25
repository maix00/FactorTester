# =============================================================================
# tools/factors/FactorExpr.py
# 因子表达式系统 — 向后兼容重导入层
#
# 核心代码已迁移到 tools/factors/expr/ 文件夹：
#   core.py, operands.py, leaf.py, rolling.py, shift.py,
#   cross_sectional.py, composite.py, conditional.py,
#   term_structure.py, signal_align.py, visual_groups.py
#
# 此文件保留以维持所有现有 import 路径不变。
# =============================================================================

# Re-export DataColumn/DataFreq for backward compatibility
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

from tools.factors.expr import (
    # core
    FactorExpr,
    EvaluateContext,
    # operands
    OperandExpr,
    # leaf
    ColumnRef,
    ParamRef,
    ConstExpr,
    _to_expr,
    # rolling
    RollingExpr,
    RollingOp,
    _rolling_argmaxmin,
    _mask_outside_trunc,
    _resolve_windows,
    # shift
    ShiftOp,
    _is_zero_shift_period,
    _strip_latex_time_subscript,
    # cross_sectional
    CrossSectionalOp,
    # composite
    CompositeExpr,
    _reduce_biop,
    expr_max,
    expr_min,
    # conditional
    WhereOp,
    # term_structure
    TermStructureOp,
    term_spread,
    term_ratio,
    term_slope,
    # signal_align
    SignalAlign,
    signal_align,
    # visual_groups
    VISUAL_OPERATOR_GROUPS,
    VISUAL_COMPOSITE_KEY,
    VISUAL_OPERATOR_CATEGORY,
    get_visual_operator_groups,
    get_visual_composite_key,
    get_visual_operator_category,
    # pre-defined column references
    OPEN,
    HIGH,
    LOW,
    CLOSE,
    VOLUME,
    TURNOVER,
    OPEN_INTEREST,
    VWAP,
    SETTLE,
    OPEN_RAW,
    HIGH_RAW,
    LOW_RAW,
    CLOSE_RAW,
    SMALL_VAL,
)
