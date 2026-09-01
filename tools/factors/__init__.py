FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from tools.factors.FactorExpr import (
        CANDIDATE,
        CURRENT,
        SMALL_VAL,
        CompositeExpr,
        ConstExpr,
        FactorExpr,
        OperandExpr,
        ParamRef,
        ShiftOp,
        SignalAlign,
        TermStructureOp,
        bar_distance,
        bar_since,
        expr_max,
        expr_min,
        scope_bars,
        scope_session,
        scope_trading_day,
        term_carry_annualized,
        term_contango,
        term_curvature,
        term_log_ratio,
        term_rank_value,
        term_ratio,
        term_slope,
        term_slope_segment,
        term_spread,
        where,
        window_bars,
    )
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.Factors import Factor
    from tools.factors.Parameters import (
        FactorFreqParam,
        FactorNextPeriodReturns,
        ReturnFreqParam,
        ReverseParam,
    )
    from tools.factors.PrecomputedFactorArtifact import PrecomputedFactorArtifact
    from tools.factors.temporal_support import (
        HACResolution,
        TemporalInference,
        TemporalSupport,
        infer_factor_input_support,
        resolve_hac_lag,
        temporal_support_for_factor,
        temporal_support_for_ic,
    )
