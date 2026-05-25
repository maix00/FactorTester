# =============================================================================
# tools/factors/expr/cross_sectional.py
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

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data.DataSource import DataSource
    from tools.data.DataMeta import DataMeta
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr

class CrossSectionalOp(OperandExpr):
    """
    一元横截面算子：CS_ZSCORE, CS_RANK 等。

    在每个时间点对横截面（所有品种）进行聚合计算。
    """

    def __init__(self, op: str, *operands: FactorExpr):
        super().__init__(op, *operands)

    @property
    def operand(self) -> FactorExpr:
        return self.operands[0]

    @property
    def left(self) -> FactorExpr:
        return self.operands[0]

    @property
    def right(self) -> FactorExpr:
        return self.operands[1]

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        vals: List[Any] = []
        for i, val in enumerate(values):
            opnd = self.operands[i]
            vals.append(opnd.value if isinstance(opnd, ConstExpr) else val)

        if self.op == 'cs_spearman':
            left_df, right_df = vals[0], vals[1]
            if not isinstance(left_df, pd.DataFrame) or not isinstance(right_df, pd.DataFrame):
                raise TypeError(
                    f"cs_spearman 需要两个 DataFrame 输入，收到 "
                    f"{type(left_df).__name__} 与 {type(right_df).__name__}"
                )
            return self._apply_spearman(left_df, right_df)

        x = vals[0]
        if self.op == 'cs_zscore':
            mean = x.mean(axis=1)
            std = x.std(axis=1)
            std = std.replace(0, np.nan)
            return x.sub(mean, axis=0).div(std, axis=0)
        if self.op == 'cs_rank':
            return x.rank(axis=1, pct=True) - 0.5
        raise ValueError(f"Unknown cross-sectional op: {self.op}")

    @staticmethod
    def _apply_spearman(left_df: pd.DataFrame, right_df: pd.DataFrame) -> pd.DataFrame:
        # 快速路径：两个 DataFrame 的 MultiIndex 和 columns 完全相同时，
        # 跳过昂贵的 .loc[common_idx, common_cols]（节省 ~2s 的 index intersection + reindex）
        if left_df.index.equals(right_df.index) and left_df.columns.equals(right_df.columns):
            idx = left_df.index
            cols = left_df.columns
            l_df = left_df
            r_df = right_df
        else:
            common_idx = pd.Index(left_df.index).intersection(pd.Index(right_df.index))
            common_cols = left_df.columns.intersection(right_df.columns)
            if len(common_idx) == 0 or len(common_cols) == 0:
                empty_idx = pd.Index([], name=left_df.index.names[-1] if left_df.index.names else None)
                result = pd.DataFrame({'IC': []}, index=empty_idx)
                result.index.names = left_df.index.names
                return result
            idx = common_idx
            cols = common_cols
            l_df = left_df.loc[idx, cols]
            r_df = right_df.loc[idx, cols]

        # Spearman = Pearson(rank(x), rank(y)); 按行（横截面）一次性向量化计算。
        valid = l_df.notna() & r_df.notna()
        l_rank = l_df.where(valid).rank(axis=1, method='average', na_option='keep')
        r_rank = r_df.where(valid).rank(axis=1, method='average', na_option='keep')

        x = l_rank.to_numpy(dtype=float)
        y = r_rank.to_numpy(dtype=float)
        mask = ~np.isnan(x) & ~np.isnan(y)

        x_masked = np.where(mask, x, 0.0)
        y_masked = np.where(mask, y, 0.0)

        n = mask.sum(axis=1).astype(float)
        sum_x = x_masked.sum(axis=1)
        sum_y = y_masked.sum(axis=1)
        sum_x2 = (x_masked * x_masked).sum(axis=1)
        sum_y2 = (y_masked * y_masked).sum(axis=1)
        sum_xy = (x_masked * y_masked).sum(axis=1)

        num = n * sum_xy - sum_x * sum_y
        den = np.sqrt((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y))

        with np.errstate(divide='ignore', invalid='ignore'):
            ic = num / den

        ic[(n <= 1) | (den <= 0)] = np.nan

        result = pd.DataFrame({'IC': ic}, index=idx)
        result.index.names = left_df.index.names
        return result

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        if self.op == 'cs_spearman':
            left_latex = self.left._to_latex(subst)
            right_latex = self.right._to_latex(subst)
            return f'\\rho_s({left_latex}, {right_latex})'

        operand_latex = self.operand._to_latex(subst)
        _LATEX_MAP = {
            'cs_zscore': f'Z({operand_latex})',
            'cs_rank': f'\\text{{Rank}}({operand_latex})',
        }
        return _LATEX_MAP.get(self.op, f'\\text{{{self.op}}}({operand_latex})')

    def _get_alias(self) -> str:
        if self.op == 'cs_spearman':
            return f"{self.op}_{self.left._get_alias()}_{self.right._get_alias()}"
        return f"{self.op}_{self.operand._get_alias()}"


# ═════════════════════════════════════════════════════════════════════════════
# Layer 6: 复合表达式（二元运算树节点）
# ═════════════════════════════════════════════════════════════════════════════

