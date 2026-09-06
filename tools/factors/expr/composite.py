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
            'latex': '\\max',
            'nop': 2,
            'func': lambda a, b: apply_pointwise('bimax', (a, b)),
        },
        'bimin': {
            'symb': 'min',
            'latex': '\\min',
            'nop': 2,
            'func': lambda a, b: apply_pointwise('bimin', (a, b)),
        },
    }

    _Ops = {
        'add': {'symb': '+', 'latex': '+', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('add', (a, b))},
        'sub': {'symb': '-', 'latex': '-', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('sub', (a, b))},
        'mul': {'symb': '*', 'latex': '\\times', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('mul', (a, b))},
        'div': {'symb': '/', 'latex': '\\frac', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('div', (a, b))},
        'gt': {'symb': '>', 'latex': '>', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('gt', (a, b))},
        'lt': {'symb': '<', 'latex': '<', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('lt', (a, b))},
        'ge': {'symb': '>=', 'latex': '\\ge', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('ge', (a, b))},
        'le': {'symb': '<=', 'latex': '\\le', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('le', (a, b))},
        'eq': {'symb': '==', 'latex': '=', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('eq', (a, b))},
        'ne': {'symb': '!=', 'latex': '\\neq', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('ne', (a, b))},
        'and': {'symb': '&', 'latex': '\\wedge', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('and', (a, b))},
        'or': {'symb': '|', 'latex': '\\vee', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('or', (a, b))},
        'neg': {'symb': '-', 'latex': '-', 'nop': 1, 'func': lambda a, *args: apply_pointwise('neg', (a,))},
        'abs': {'symb': 'abs', 'latex': '\\mathrm{abs}', 'nop': 1, 'func': lambda a, *args: apply_pointwise('abs', (a,))},
        'not': {'symb': '~', 'latex': '\\neg', 'nop': 1, 'func': lambda a, *args: apply_pointwise('not', (a,))},
        'log': {'symb': 'log', 'latex': '\\log', 'nop': 1, 'func': lambda a, *args: apply_pointwise('log', (a,))},
        'sign': {'symb': 'sign', 'latex': '\\mathrm{sign}', 'nop': 1, 'func': lambda a, *args: apply_pointwise('sign', (a,))},
        'sqrt': {'symb': 'sqrt', 'latex': '\\sqrt', 'nop': 1, 'func': lambda a, *args: apply_pointwise('sqrt', (a,))},
        'tanh': {'symb': 'tanh', 'latex': '\\tanh', 'nop': 1, 'func': lambda a, *args: apply_pointwise('tanh', (a,))},
        'pow': {'symb': '**', 'latex': '^', 'nop': 2, 'func': lambda a, b, *args: apply_pointwise('pow', (a, b))},
        'max': {'symb': 'max', 'latex': '\\max', 'nop': -1, 'func': lambda *args: _reduce_biop('bimax', args)},
        'min': {'symb': 'min', 'latex': '\\min', 'nop': -1, 'func': lambda *args: _reduce_biop('bimin', args)},
    }

    _LATEX_PRECEDENCE = {
        'or': 10,
        'and': 20,
        'gt': 30, 'lt': 30, 'ge': 30, 'le': 30, 'eq': 30, 'ne': 30,
        'add': 40, 'sub': 40,
        'mul': 50, 'div': 50,
        'pow': 60,
        'neg': 70, 'abs': 70, 'not': 70, 'log': 70, 'sign': 70, 'sqrt': 70, 'tanh': 70,
        'max': 80, 'min': 80,
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

    def _to_latex(self, subst: dict | None = None) -> str:
        sk = self._structural_key()
        if subst is not None and sk in subst:
            return f"{subst[sk]}_t"
        operands_latex = [opnd._to_latex(subst) for opnd in self.operands]
        if self.op in self._biOps:
            op_latex = self._biOps[self.op]['latex']
            return f'{op_latex}\\left({operands_latex[0]}, {operands_latex[1]}\\right)'
        if self.op in self._Ops:
            if self._Ops[self.op]['nop'] == 1:
                operand_latex = operands_latex[0]
                operator = self._Ops[self.op]['latex']
                # Factor construction represents $Rev as neg(SignalAlign).
                # Natural negation inside the source expression stays black.
                if self.op == 'neg' and getattr(self.operands[0], 'op', None) == 'SIGNAL_ALIGN':
                    operator = r'\textcolor{red}{-}'
                return f"{operator}\\left({operand_latex}\\right)"
            elif self._Ops[self.op]['nop'] == 2:
                left_latex = self._binary_operand_latex(self.operands[0], operands_latex[0], side='left', subst=subst)
                right_latex = self._binary_operand_latex(self.operands[1], operands_latex[1], side='right', subst=subst)
                if self.op in ('add', 'sub', 'mul', 'pow', 'gt', 'lt', 'ge', 'le', 'eq', 'ne', 'and', 'or'):
                    return f'{left_latex} {self._Ops[self.op]["latex"]} {right_latex}'
                elif self.op in ('div'):
                    return f'{self._Ops[self.op]["latex"]}{{{left_latex}}}{{{right_latex}}}'
                else:
                    return f'{self._Ops[self.op]["latex"]}\\left({left_latex}, {right_latex}\\right)'
            else:
                return f'{self._Ops[self.op]["latex"]}\\left({", ".join(operands_latex)}\\right)'
        else:
            return f'\\text{{{self.op.capitalize()}}}\\left({", ".join(operands_latex)}\\right)'

    @classmethod
    def _expr_precedence(cls, expr: FactorExpr) -> int:
        if not isinstance(expr, CompositeExpr):
            return 10_000
        return cls._LATEX_PRECEDENCE.get(expr.op, 0)

    def _needs_parenthesis(self, child: FactorExpr, side: str, subst: dict | None = None) -> bool:
        if not isinstance(child, CompositeExpr):
            return False
        if subst is not None and child._structural_key() in subst:
            return False
        if self.op == 'div':
            return False

        parent_prec = self._LATEX_PRECEDENCE.get(self.op, 0)
        child_prec = self._expr_precedence(child)

        if child_prec < parent_prec:
            return True
        if child_prec > parent_prec:
            return False

        # 同优先级时按算子特性处理，保证树结构语义不丢失。
        if self.op == 'sub' and side == 'right':
            return True
        if self.op == 'pow':
            return True
        if self.op == 'mul' and child.op == 'div':
            return True
        if self.op in ('gt', 'lt', 'ge', 'le', 'eq', 'ne', 'and', 'or'):
            return True
        return False

    def _binary_operand_latex(self, child: FactorExpr, child_latex: str, side: str, subst: dict | None = None) -> str:
        return f'\\left({child_latex}\\right)' if self._needs_parenthesis(child, side, subst=subst) else child_latex

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
