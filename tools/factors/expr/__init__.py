# =============================================================================
# tools/factors/expr/__init__.py
# 因子表达式系统 — 统一导出
# =============================================================================

FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from .core import EvaluateContext, FactorExpr
    from .timeline import PanelTimeline, build_panel_timeline, compact_observed, scatter_observed
    from .operands import OperandExpr
    from .leaf import CategoryBoolRef, ColumnRef, ParamRef, ConstExpr, _to_expr
    from .rolling import (
        RollingExpr,
        RollingOp,
        WindowBarsExpr,
        _mask_outside_trunc,
        _resolve_windows,
        _rolling_argmaxmin,
        window_bars,
    )
    from .shift import ShiftOp, _is_zero_shift_period, _strip_latex_time_subscript
    from .cross_sectional import CrossSectionalOp
    from .composite import CompositeExpr, _reduce_biop, expr_max, expr_min
    from .conditional import WhereOp, where
    from .term_structure import (
        TermStructureOp,
        term_carry_annualized,
        term_contango,
        term_curvature,
        term_log_ratio,
        term_rank_value,
        term_ratio,
        term_slope,
        term_slope_segment,
        term_spread,
    )
    from .signal_align import SignalAlign, signal_align
    from .visual_groups import (
        VISUAL_OPERATOR_GROUPS,
        VISUAL_COMPOSITE_KEY,
        VISUAL_OPERATOR_CATEGORY,
        get_visual_operator_groups,
        get_visual_composite_key,
        get_visual_operator_category,
    )

    # ═════════════════════════════════════════════════════════════════════════
    # 预定义常用列引用（在所有子模块加载后定义，避免循环导入）
    # ═════════════════════════════════════════════════════════════════════════

    from tools.data.types import DataColumn

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

__factor_workspace__ = (
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
)
