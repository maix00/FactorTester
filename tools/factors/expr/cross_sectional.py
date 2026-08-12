# =============================================================================
# tools/factors/expr/cross_sectional.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import pandas as pd
from typing import Any, List


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr
from .cross_sectional_group import apply_group_transform, eligibility_mask, ordinal_rank, zscore
from .cross_sectional_statistics import correlation
from .cross_sectional_residual import residualize

class CrossSectionalOp(OperandExpr):
    """
    一元横截面算子：CS_ZSCORE, CS_RANK 等。

    在每个时间点对横截面（所有品种）进行聚合计算。
    """

    def __init__(self, op: str, *operands: FactorExpr, category: Any = None, exposure_count: int | None = None):
        super().__init__(op, *operands)
        self.category = category
        self.exposure_count = exposure_count

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        return CrossSectionalOp(self.op, *(operand.resolve(*args, **kwargs) for operand in self.operands), category=self.category, exposure_count=self.exposure_count)

    def _structural_extra(self) -> tuple:
        extra = []
        if self.category is not None:
            extra.append((self.category.alias, getattr(self.category, '_definition_key', None)))
        if self.exposure_count is not None:
            extra.append(self.exposure_count)
        return tuple(extra)

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

        if self.op in ('cs_spearman', 'cs_corr'):
            left_df, right_df = vals[0], vals[1]
            if not isinstance(left_df, pd.DataFrame) or not isinstance(right_df, pd.DataFrame):
                raise TypeError(
                    f"{self.op} 需要两个 DataFrame 输入，收到 "
                    f"{type(left_df).__name__} 与 {type(right_df).__name__}"
                )
            return correlation(left_df, right_df, spearman=self.op == 'cs_spearman')
        if self.op == 'cs_residualize':
            count = self.exposure_count or 0
            return residualize(vals[0], vals[1:1 + count], vals[1 + count])

        x = vals[0]
        if self.op == 'cs_zscore':
            return zscore(x)
        if self.op == 'cs_rank':
            return x.rank(axis=1, pct=True) - 0.5
        if self.op == 'cs_rank_masked':
            if len(vals) != 2:
                raise TypeError("cs_rank_masked 需要值和 eligibility mask 两个输入")
            return x.where(eligibility_mask(vals[1], x)).rank(axis=1, pct=True) - 0.5
        if self.op in ('cs_ordinal_rank_asc', 'cs_ordinal_rank_desc'):
            if len(vals) != 2:
                raise TypeError(f"{self.op} 需要值和 eligibility mask 两个输入")
            return ordinal_rank(
                x,
                vals[1],
                ascending=self.op == 'cs_ordinal_rank_asc',
            )
        if self.op in ('cs_group_rank', 'cs_group_zscore', 'cs_group_demean'):
            if self.category is None or len(vals) != 2:
                raise TypeError(f"{self.op} requires Category and eligibility mask")
            return apply_group_transform(self.op, x, vals[1], self.category)
        raise ValueError(f"Unknown cross-sectional op: {self.op}")

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        if self.op == 'cs_spearman':
            left_latex = self.left._to_latex(subst)
            right_latex = self.right._to_latex(subst)
            return f'\\rho_s({left_latex}, {right_latex})'
        if self.op == 'cs_corr':
            left_latex = self.left._to_latex(subst)
            right_latex = self.right._to_latex(subst)
            return f'\\rho({left_latex}, {right_latex})'

        operand_latex = self.operand._to_latex(subst)
        _LATEX_MAP = {
            'cs_zscore': f'Z({operand_latex})',
            'cs_rank': f'\\text{{Rank}}({operand_latex})',
            'cs_rank_masked': f'\\text{{Rank}}_{{mask}}({operand_latex})',
            'cs_ordinal_rank_asc': f'\\text{{OrdinalRank}}_\\uparrow({operand_latex})',
            'cs_ordinal_rank_desc': f'\\text{{OrdinalRank}}_\\downarrow({operand_latex})',
        }
        return _LATEX_MAP.get(self.op, f'\\text{{{self.op}}}({operand_latex})')

    def _get_alias(self) -> str:
        if self.op in ('cs_spearman', 'cs_corr'):
            return f"{self.op}_{self.left._get_alias()}_{self.right._get_alias()}"
        if self.op in ('cs_ordinal_rank_asc', 'cs_ordinal_rank_desc'):
            return f"{self.op}_{self.operand._get_alias()}_mask_{self.right._get_alias()}"
        if self.op == 'cs_rank_masked':
            return f"{self.op}_{self.operand._get_alias()}_mask_{self.right._get_alias()}"
        return f"{self.op}_{self.operand._get_alias()}"


# ═════════════════════════════════════════════════════════════════════════════
# Layer 6: 复合表达式（二元运算树节点）
# ═════════════════════════════════════════════════════════════════════════════
