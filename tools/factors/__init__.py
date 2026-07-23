FACTOR_WORKSPACE = True

if FACTOR_WORKSPACE:
    from tools.factors.Parameters import (
        FactorNextPeriodReturns,
        ReturnFreqParam,
        FactorFreqParam,
        ReverseParam,
    )
    from tools.factors.Factors import Factor
    from tools.factors.FactorFamily import FactorFamily
    from tools.factors.PrecomputedFactorArtifact import PrecomputedFactorArtifact
    from tools.factors.FactorExpr import (
        FactorExpr,
        ConstExpr,
        ParamRef,
        OperandExpr,
        CompositeExpr,
        ShiftOp,
        SignalAlign,
        TermStructureOp,
        expr_max,
        expr_min,
        term_carry_annualized,
        term_contango,
        term_curvature,
        term_log_ratio,
        term_rank_value,
        term_spread,
        term_ratio,
        term_slope,
        term_slope_segment,
        where,
        SMALL_VAL,
    )
