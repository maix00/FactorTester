# =============================================================================
# tools/factors/expr/__init__.py
# 因子表达式系统 — 统一导出
# =============================================================================

FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    # ═════════════════════════════════════════════════════════════════════════
    # 预定义常用列引用（在所有子模块加载后定义，避免循环导入）
    # ═════════════════════════════════════════════════════════════════════════
    from tools.data.types import DataColumn

    from .bar_search import BarDistanceOp, BarSinceOp, bar_distance, bar_since
    from .composite import CompositeExpr, _reduce_biop, expr_max, expr_min
    from .conditional import WhereOp, where
    from .core import EvaluateContext, FactorExpr
    from .cross_sectional import CrossSectionalOp
    from .leaf import CategoryBoolRef, ColumnRef, ConstExpr, ParamRef, _to_expr
    from .lookback_scope import (
        BarCountScope,
        LookbackScope,
        SessionScope,
        TradingDayScope,
        bars,
        session,
        trading_day,
    )
    from .match_refs import CANDIDATE, CURRENT, MatchValueRef
    from .operands import OperandExpr
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
    from .signal_align import SignalAlign, signal_align
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
    from .timeline import (
        PanelTimeline,
        build_panel_timeline,
        compact_observed,
        scatter_observed,
    )
    from .visual_groups import (
        VISUAL_COMPOSITE_KEY,
        VISUAL_OPERATOR_CATEGORY,
        VISUAL_OPERATOR_GROUPS,
        get_visual_composite_key,
        get_visual_operator_category,
        get_visual_operator_groups,
    )

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
    "CURRENT",
    "CANDIDATE",
    "bars",
    "session",
    "trading_day",
    "bar_since",
    "bar_distance",
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
