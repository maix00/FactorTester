"""Per-timestamp cross-sectional OLS residualization."""
from __future__ import annotations

from typing import Any, Sequence
import numpy as np
import pandas as pd
from .cross_sectional_group import eligibility_mask


def residualize(signal: pd.DataFrame, exposures: Sequence[pd.DataFrame], mask: Any) -> pd.DataFrame:
    aligned = [item.reindex(index=signal.index, columns=signal.columns) for item in exposures]
    eligible = eligibility_mask(mask, signal).to_numpy(dtype=bool)
    y = signal.to_numpy(dtype=float)
    x = np.stack([item.to_numpy(dtype=float) for item in aligned], axis=2)
    result = np.full(y.shape, np.nan, dtype=float)
    for row in range(y.shape[0]):
        valid = eligible[row] & np.isfinite(y[row]) & np.isfinite(x[row]).all(axis=1)
        if valid.sum() <= len(exposures) + 1:
            continue
        design = np.column_stack([np.ones(valid.sum()), x[row, valid]])
        beta, *_ = np.linalg.lstsq(design, y[row, valid], rcond=None)
        result[row, valid] = y[row, valid] - design @ beta
    return pd.DataFrame(result, index=signal.index, columns=signal.columns)
