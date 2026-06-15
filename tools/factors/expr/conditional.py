# =============================================================================
# tools/factors/expr/conditional.py
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

from tools.data.types.DataColumn import DataColumn
from tools.data.types.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext, _lazy
from .operands import OperandExpr

class WhereOp(OperandExpr):
    """
    where(cond, a, b)

    Used for research-style universe filtering:
      Final = CCS.where(Illiq <= Illiq.cs_quantile(0.5), np.nan)

    Broadcast rules:
      - Panel(DataFrame) where TimeSeries(Series[bool]) → broadcast by index (axis=0)
      - Panel(DataFrame) where TimeSeries(Series) for `b` → broadcast by index (axis=0)
    """

    def _apply_op(self, values: List[Any]) -> Any:
        cond, a, b = values

        if isinstance(a, pd.DataFrame):
            if isinstance(cond, pd.DataFrame):
                cond_df = cond.reindex(index=a.index, columns=a.columns)
            elif isinstance(cond, pd.Series):
                mask = _lazy()['CompositeExpr']._df_series_broadcast(a, cond).astype(bool)
                cond_df = pd.DataFrame(mask, index=a.index, columns=a.columns)
            else:
                cond_df = pd.DataFrame(bool(cond), index=a.index, columns=a.columns)

            if isinstance(b, pd.Series):
                b_arr = _lazy()['CompositeExpr']._df_series_broadcast(a, b)
                b = pd.DataFrame(b_arr, index=a.index, columns=a.columns)

            return a.where(cond_df, other=b)

        if isinstance(a, pd.Series):
            if isinstance(cond, pd.DataFrame):
                cond_s = cond.iloc[:, 0]
            elif isinstance(cond, pd.Series):
                cond_s = cond
            else:
                cond_s = pd.Series(bool(cond), index=a.index)
            return a.where(cond_s, other=b)

        return a if bool(cond) else b


# ═════════════════════════════════════════════════════════════════════════════
# 顶层便利函数：max / min 多元聚合
# ═════════════════════════════════════════════════════════════════════════════
