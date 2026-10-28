# =============================================================================
# tools/factors/expr/composite.py
# 因子表达式系统 — 从 FactorExpr.py 拆分
# =============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any, List, cast


from .core import FactorExpr
from .operands import OperandExpr
from .leaf import ConstExpr
from .pointwise import (
    align_series,
    apply_binary,
    apply_pointwise,
    broadcast_series_to_frame,
)

def _reduce_biop(op: str, args: tuple) -> Any:
    """从左到右依次用 _biOps[op] 折叠 args，正确处理 DataFrame+scalar 混合。"""
    return apply_pointwise(op, args)


class CompositeExpr(OperandExpr):
    """
    复合表达式 — 元素级多元运算。

    支持：
      - add, sub, mul, div（算术）
      - gt, lt, ge, le, eq, ne（比较）
      - and, or（逻辑）
      - max, min, pow（多元聚合）
    - neg, abs, not, log, sign, sqrt（一元）
    """

    @staticmethod
    def _df_series_broadcast(df: pd.DataFrame, s: pd.Series) -> np.ndarray:
        """Broadcast a (T,) Series to (T,P) ndarray matching df (by index)."""
        return broadcast_series_to_frame(df, s)

    @staticmethod
    def _series_align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
        return align_series(a, b)

    @staticmethod
    def _binop(a: Any, b: Any, op: str) -> Any:
        """
        Binary op with TimeSeries (pd.Series) broadcast support.

        Pandas default DataFrame op Series aligns the Series on columns, which is not what we want
        for TimeSeries (indexed by time). Here we broadcast by index (axis=0) when:
          - one operand is DataFrame (T×P)
          - the other is Series (T,)
        """
        return apply_binary(a, b, op)

    _biOps = {
        'bimax': {
            'symb': 'max',
            'nop': 2,
            'func': lambda a, b: apply_pointwise('bimax', (a, b)),
        },
        'bimin': {
            'symb': 'min',
            'nop': 2,
            'func': lambda a, b: apply_pointwise('bimin', (a, b)),
        },
    }

    _Ops = {
        'add': {'symb': '+', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('add', (a, b))},
        'sub': {'symb': '-', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('sub', (a, b))},
        'mul': {'symb': '*', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('mul', (a, b))},
        'div': {'symb': '/', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('div', (a, b))},
        'gt': {'symb': '>', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('gt', (a, b))},
        'lt': {'symb': '<', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('lt', (a, b))},
        'ge': {'symb': '>=', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('ge', (a, b))},
        'le': {'symb': '<=', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('le', (a, b))},
        'eq': {'symb': '==', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('eq', (a, b))},
        'ne': {'symb': '!=', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('ne', (a, b))},
        'and': {'symb': '&', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('and', (a, b))},
        'or': {'symb': '|', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('or', (a, b))},
        'neg': {'symb': '-', 'nop': 1, 'func': lambda a, *args: apply_pointwise('neg', (a,))},
        'abs': {'symb': 'abs', 'nop': 1, 'func': lambda a, *args: apply_pointwise('abs', (a,))},
        'not': {'symb': '~', 'nop': 1, 'func': lambda a, *args: apply_pointwise('not', (a,))},
        'log': {'symb': 'log', 'nop': 1, 'func': lambda a, *args: apply_pointwise('log', (a,))},
        'sign': {'symb': 'sign', 'nop': 1, 'func': lambda a, *args: apply_pointwise('sign', (a,))},
        'sqrt': {'symb': 'sqrt', 'nop': 1, 'func': lambda a, *args: apply_pointwise('sqrt', (a,))},
        'tanh': {'symb': 'tanh', 'nop': 1, 'func': lambda a, *args: apply_pointwise('tanh', (a,))},
        'pow': {'symb': '**', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('pow', (a, b))},
        'max': {'symb': 'max', 'nop': -1, 'func': lambda *args: _reduce_biop('bimax', args)},
        'min': {'symb': 'min', 'nop': -1, 'func': lambda *args: _reduce_biop('bimin', args)},
    }


    def __new__(cls, op: str, *operands: FactorExpr, **kwargs) -> 'FactorExpr':
        """表达式规范化：常量折叠 + 等价化简，在构造前归并。

        常量折叠：所有 operand 为 ConstExpr → 直接求值为 ConstExpr。
        等价化简：
          - neg(neg(a))         → a
          - neg(sub(a, b))      → sub(b, a)
          - add(a, Const(0))    → a
          - sub(a, Const(0))    → a
          - mul(a, Const(1))    → a
          - mul(a, Const(0))    → Const(0)
          - div(a, Const(1))    → a
          - pow(a, Const(1))    → a
          - pow(a, Const(0))    → Const(1)
          - sub(a, Const(c))    → add(a, Const(-c))
          - div(a, Const(c))    → mul(a, Const(1/c))
        """
        # ── 常量折叠 ──
        if operands and all(isinstance(opnd, ConstExpr) for opnd in operands):
            values = [cast(ConstExpr, opnd).value for opnd in operands]
            if op in cls._Ops:
                result = cls._Ops[op]['func'](*values)
                return ConstExpr(result)
            if op in cls._biOps:
                result = cls._biOps[op]['func'](*values)
                return ConstExpr(result)

        # ── 等价化简 ──
        if op == 'neg' and len(operands) == 1:
            inner = operands[0]
            if isinstance(inner, CompositeExpr):
                # neg(neg(a)) → a
                if inner.op == 'neg':
                    return inner.operands[0]
                # neg(sub(a, b)) → sub(b, a)
                if inner.op == 'sub':
                    return CompositeExpr('sub', inner.operands[1], inner.operands[0])

        # ── 身份消元 / 常量优化 ──
        if len(operands) == 2 and isinstance(operands[1], ConstExpr):
            c = cast(ConstExpr, operands[1]).value
            a = operands[0]
            if op == 'add' and c == 0:
                return a
            if op == 'sub' and c == 0:
                return a
            if op == 'mul':
                if c == 1:
                    return a
                if c == 0:
                    return ConstExpr(0)
            if op == 'div' and c == 1:
                return a
            if op == 'pow':
                if c == 1:
                    return a
                if c == 0:
                    return ConstExpr(1)

        # sub(a, Const(c)) → add(a, Const(-c))
        if op == 'sub' and len(operands) == 2:
            if isinstance(operands[1], ConstExpr):
                v = cast(ConstExpr, operands[1]).value
                try:
                    neg_v = -v
                    return cls.__new__(cls, 'add', operands[0], ConstExpr(neg_v))
                except (TypeError, ValueError):
                    pass

        # div(a, Const(c)) → mul(a, Const(1/c))
        if op == 'div' and len(operands) == 2:
            if isinstance(operands[1], ConstExpr):
                v = cast(ConstExpr, operands[1]).value
                try:
                    inv_v = 1.0 / v
                    return cls.__new__(cls, 'mul', operands[0], ConstExpr(inv_v))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

        return super().__new__(cls)

    def __init__(self, op: str, *operands: FactorExpr):
        super().__init__(op, *operands)

    def _apply_op(self, values: List[Any]) -> pd.DataFrame:
        """根据 op 类型执行实际运算（由 OperandExpr.evaluate 调用）。"""
        if self.op in self._biOps:
            return self._biOps[self.op]['func'](*values)
        if self.op in self._Ops:
            return self._Ops[self.op]['func'](*values)
        raise ValueError(f"Unknown op: {self.op}")

    @property
    def op_name(self) -> str:
        if self.op in self._biOps:
            return self._biOps[self.op]['symb']
        if self.op in self._Ops:
            return self._Ops[self.op]['symb']
        return self.op





    def _get_alias(self) -> str:
        op_aliases = {
            'add': 'ADD', 'sub': 'SUB', 'mul': 'MUL', 'div': 'DIV',
            'gt': 'GT', 'lt': 'LT', 'ge': 'GE', 'le': 'LE',
            'eq': 'EQ', 'ne': 'NE',
            'and': 'AND', 'or': 'OR',
            'neg': 'NEG', 'abs': 'ABS', 'not': 'NOT',
            'log': 'LOG', 'sign': 'SIGN', 'sqrt': 'SQRT', 'tanh': 'TANH',
            'bimax': 'MAX', 'bimin': 'MIN',
        }
        op_alias = op_aliases.get(self.op, self.op.upper())
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{op_alias}_{'_'.join(parts)}"


# ═════════════════════════════════════════════════════════════════════════════
# 顶层便利函数：max / min 多元聚合
# ═════════════════════════════════════════════════════════════════════════════

def expr_max(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最大值。"""
    if len(exprs) == 0:
        raise ValueError("expr_max requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    return CompositeExpr('max', *exprs)


def expr_min(*exprs: FactorExpr) -> FactorExpr:
    """多元逐元素最小值。"""
    if len(exprs) == 0:
        raise ValueError("expr_min requires at least one argument")
    if len(exprs) == 1:
        return exprs[0]
    return CompositeExpr('min', *exprs)
