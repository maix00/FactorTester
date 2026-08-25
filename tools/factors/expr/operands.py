# =============================================================================
# tools/factors/expr/operands.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import pandas as pd
from typing import (
    TYPE_CHECKING, Any, List, Sequence, Tuple
)


if TYPE_CHECKING:
    pass


from .core import FactorExpr, EvaluateContext, semantic_structural_key

class OperandExpr(FactorExpr):
    """
    多元算子基类 — 所有含有子表达式的节点继承此类。

    核心设计：
      - __init__(op, *operands) 存储操作名和子表达式元组
      - _operands 属性自动从 self.operands 派生
      - evaluate() 递归求值所有子表达式 → 调用 _apply_op(values)
      - 子类只需覆盖 _apply_op() 和展示方法（op_name/to_latex/_get_alias）

    dependencies / param_deps 均复用 FactorExpr 基类的树遍历实现。
    """

    def __init__(self, op: str, *operands: 'FactorExpr'):
        self.op = op
        self.operands: Tuple[FactorExpr, ...] = operands

    @property
    def _operands(self) -> Sequence['FactorExpr']:
        return self.operands

    def resolve(self, *args, **kwargs) -> 'FactorExpr':
        resolved_operands = [opnd.resolve(*args, **kwargs) for opnd in self._operands]
        resolved = type(self)(self.op, *resolved_operands)
        if self._is_intermediate:
            resolved = resolved.as_intermediate(self._intermediate_name, factor=kwargs.get('caller', None))
        return resolved

    # ── 通用求值 ──

    def _evaluate(self, ctx: EvaluateContext) -> pd.DataFrame:
        values = [opnd.evaluate(ctx=ctx) for opnd in self.operands]
        result = self._apply_op(values)
        return result

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """子类覆盖：对已求值的 operands DataFrame 执行核心运算。"""
        raise NotImplementedError

    # ── 展示方法 ──

    @property
    def op_name(self) -> str:
        return self.op.upper()

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        parts = [opnd._to_latex(subst) for opnd in self.operands]
        return f'\\text{{{self.op}}}({", ".join(parts)})'

    def _get_alias(self) -> str:
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{self.op.upper()}_{'_'.join(parts)}"

    # ── 结构等价（FactorData 去重 key） ──

    def _structural_key(self) -> tuple:
        """
        OperandExpr 的结构 key。

        子类可通过覆盖 _structural_extra() 添加 op 之外的结构信息
        （如 RollingOp 需要 window, ShiftOp 需要 periods）。

        对称运算（add, mul, max, min, and, or, eq, ne,
        cs_spearman, cs_corr, cs_cov）的 operands 排序后取 key，
        保证 a+b ≡ b+a, max(a,b,c) ≡ max(c,a,b) 等。
        """
        type_tag = type(self).__name__
        op_tag = self.op
        op_keys_raw = [opnd._structural_key() for opnd in self._operands]
        if op_tag in FactorExpr._SYMMETRIC_OPS:
            op_keys = tuple(sorted(op_keys_raw, key=semantic_structural_key))
        else:
            op_keys = tuple(op_keys_raw)
        extra = self._structural_extra()
        return (type_tag, op_tag, op_keys) + extra

    def _structural_extra(self) -> tuple:
        """子类覆盖：返回除 op + operands 外的额外结构信息。"""
        return ()


# ═════════════════════════════════════════════════════════════════════════════
# Layer 2: 叶子节点
# ═════════════════════════════════════════════════════════════════════════════
