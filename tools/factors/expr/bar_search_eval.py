"""Scalar default transport only. Search evaluation is owned by the Rust Plan."""
import numpy as np
from .core import FactorExpr
from .leaf import ConstExpr

def scalar_default(expr: FactorExpr) -> float | None:
    if type(expr).__name__ == "ScopeLengthDefault":
        return None
    if not isinstance(expr, ConstExpr) or not np.isscalar(expr.value):
        raise TypeError("bar search default must resolve to a scalar constant")
    return float(expr.value)



def _observed_mask(frame: pd.DataFrame, ctx: EvaluateContext) -> np.ndarray:
    if ctx.panel_timeline is None:
        return np.ones(frame.shape, dtype=bool)
    return ctx.panel_timeline.observed_mask.reindex(
        index=frame.index, columns=frame.columns, fill_value=False,
    ).to_numpy(dtype=bool)
