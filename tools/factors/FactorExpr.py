# =============================================================================
# tools/factors/FactorExpr.py
# 因子表达式系统 — 向后兼容重导入层
#
# 核心代码已迁移到 tools/factors/expr/ 文件夹：
#   core.py, operands.py, leaf.py, pointwise.py, rolling.py, shift.py,
#   cross_sectional.py, composite.py, conditional.py,
#   term_structure.py, signal_align.py, visual_groups.py
#
# 此文件保留以维持所有现有 import 路径不变。
# =============================================================================

FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    # Re-export DataColumn/DataFreq for backward compatibility
    from tools.data.types import DataColumn
    from tools.data.types import DataFreq

    from tools.factors.expr import (
        # core
        EvaluateContext,
        FactorExpr,
        PanelTimeline,
        build_panel_timeline,
        compact_observed,
        scatter_observed,
        # operands
        OperandExpr,
        # leaf
        CategoryBoolRef,
        ColumnRef,
        ParamRef,
        ConstExpr,
        _to_expr,
        # rolling
        RollingExpr,
        RollingOp,
        WindowBarsExpr,
        _rolling_argmaxmin,
        _mask_outside_trunc,
        _resolve_windows,
        window_bars,
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
        where,
        # term_structure
        TermStructureOp,
        term_carry_annualized,
        term_contango,
        term_curvature,
        term_log_ratio,
        term_rank_value,
        term_spread,
        term_ratio,
        term_slope,
        term_slope_segment,
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

__all__ = [
    "DataColumn",
    "DataFreq",
    "EvaluateContext",
    "FactorExpr",
    "PanelTimeline",
    "build_panel_timeline",
    "compact_observed",
    "scatter_observed",
    "OperandExpr",
    "CategoryBoolRef",
    "ColumnRef",
    "ParamRef",
    "ConstExpr",
    "_to_expr",
    "RollingExpr",
    "RollingOp",
    "WindowBarsExpr",
    "_rolling_argmaxmin",
    "_mask_outside_trunc",
    "_resolve_windows",
    "window_bars",
    "ShiftOp",
    "_is_zero_shift_period",
    "_strip_latex_time_subscript",
    "CrossSectionalOp",
    "CompositeExpr",
    "_reduce_biop",
    "expr_max",
    "expr_min",
    "WhereOp",
    "where",
    "TermStructureOp",
    "term_carry_annualized",
    "term_contango",
    "term_curvature",
    "term_log_ratio",
    "term_rank_value",
    "term_spread",
    "term_ratio",
    "term_slope",
    "term_slope_segment",
    "SignalAlign",
    "signal_align",
    "VISUAL_OPERATOR_GROUPS",
    "VISUAL_COMPOSITE_KEY",
    "VISUAL_OPERATOR_CATEGORY",
    "get_visual_operator_groups",
    "get_visual_composite_key",
    "get_visual_operator_category",
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
