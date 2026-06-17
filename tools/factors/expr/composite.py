# =============================================================================
# tools/factors/expr/composite.py
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

from tools.data.types import DataColumn
from tools.data.types import DataFreq

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.data import DataProviderProductTS as DataSource
    from tools.data.views.ProductDataView import ProductDataView
    from tools.parameters.Parameter import Parameter


from .core import FactorExpr, EvaluateContext
from .operands import OperandExpr
from .leaf import ConstExpr, ColumnRef, _to_expr
from .cross_sectional import CrossSectionalOp

def _reduce_biop(op: str, args: tuple) -> Any:
    """从左到右依次用 _biOps[op] 折叠 args，正确处理 DataFrame+scalar 混合。"""
    result = args[0]
    bi_func = CompositeExpr._biOps[op]['func']
    for a in args[1:]:
        result = bi_func(result, a)
    return result


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
        if not df.index.equals(s.index):
            s = s.reindex(df.index)
        return s.to_numpy(dtype=float)[:, np.newaxis]

    @staticmethod
    def _series_align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
        if a.index.equals(b.index):
            return a, b
        common = a.index.intersection(b.index)
        return a.loc[common], b.loc[common]

    @staticmethod
    def _binop(a: Any, b: Any, op: str) -> Any:
        """
        Binary op with TimeSeries (pd.Series) broadcast support.

        Pandas default DataFrame op Series aligns the Series on columns, which is not what we want
        for TimeSeries (indexed by time). Here we broadcast by index (axis=0) when:
          - one operand is DataFrame (T×P)
          - the other is Series (T,)
        """
        if isinstance(a, pd.DataFrame) and isinstance(b, pd.Series):
            if op == "add": return a.add(b, axis=0)
            if op == "sub": return a.sub(b, axis=0)
            if op == "mul": return a.mul(b, axis=0)
            if op == "div": return a.div(b, axis=0)
            if op == "gt": return a.gt(b, axis=0)
            if op == "lt": return a.lt(b, axis=0)
            if op == "ge": return a.ge(b, axis=0)
            if op == "le": return a.le(b, axis=0)
            if op == "eq": return a.eq(b, axis=0)
            if op == "ne": return a.ne(b, axis=0)
            if op == "and": return a.__and__(b, axis=0)  # type: ignore[arg-type]
            if op == "or": return a.__or__(b, axis=0)    # type: ignore[arg-type]
        if isinstance(a, pd.Series) and isinstance(b, pd.DataFrame):
            # flip, then apply (keeping operation direction for non-commutative ops)
            if op == "sub":
                return (b.rsub(a, axis=0))
            if op == "div":
                return (b.rdiv(a, axis=0))
            if op == "gt":
                return (b.lt(a, axis=0))
            if op == "lt":
                return (b.gt(a, axis=0))
            if op == "ge":
                return (b.le(a, axis=0))
            if op == "le":
                return (b.ge(a, axis=0))
            # commutative / symmetric
            if op == "add": return b.add(a, axis=0)
            if op == "mul": return b.mul(a, axis=0)
            if op == "eq": return b.eq(a, axis=0)
            if op == "ne": return b.ne(a, axis=0)
            if op == "and": return b.__and__(a, axis=0)  # type: ignore[arg-type]
            if op == "or": return b.__or__(a, axis=0)    # type: ignore[arg-type]
        # Series-Series: align by index
        if isinstance(a, pd.Series) and isinstance(b, pd.Series):
            aa, bb = CompositeExpr._series_align(a, b)
            if op == "add": return aa + bb
            if op == "sub": return aa - bb
            if op == "mul": return aa * bb
            if op == "div": return aa / bb
            if op == "gt": return aa > bb
            if op == "lt": return aa < bb
            if op == "ge": return aa >= bb
            if op == "le": return aa <= bb
            if op == "eq": return aa == bb
            if op == "ne": return aa != bb
            if op == "and": return aa & bb
            if op == "or": return aa | bb
        # Fallback: let pandas/numpy handle it (scalars, df-df, df-scalar, etc.)
        if op == "add": return a + b
        if op == "sub": return a - b
        if op == "mul": return a * b
        if op == "div": return a / b
        if op == "gt": return a > b
        if op == "lt": return a < b
        if op == "ge": return a >= b
        if op == "le": return a <= b
        if op == "eq": return a == b
        if op == "ne": return a != b
        if op == "and": return a & b
        if op == "or": return a | b
        raise ValueError(op)

    _biOps = {
        'bimax': {
            'symb': 'max',
            'latex': '\\max',
            'nop': 2,
            'func': lambda a, b: (
                (
                    pd.DataFrame(
                        np.maximum(a.values, CompositeExpr._df_series_broadcast(a, b)),
                        index=a.index,
                        columns=a.columns,
                    )
                    if isinstance(a, pd.DataFrame) and isinstance(b, pd.Series)
                    else (
                        pd.DataFrame(
                            np.maximum(CompositeExpr._df_series_broadcast(b, a), b.values),
                            index=b.index,
                            columns=b.columns,
                        )
                        if isinstance(a, pd.Series) and isinstance(b, pd.DataFrame)
                        else (
                            (lambda aa, bb: pd.Series(np.maximum(aa.values, bb.values), index=aa.index))(
                                *CompositeExpr._series_align(a, b)
                            )
                            if isinstance(a, pd.Series) and isinstance(b, pd.Series)
                            else (
                                a.clip(lower=b)  # type: ignore[arg-type]
                                if isinstance(a, pd.DataFrame) and np.isscalar(b)
                                else (
                                    b.clip(lower=a)  # type: ignore[arg-type]
                                    if isinstance(b, pd.DataFrame) and np.isscalar(a)
                                    else (
                                        np.maximum(a, b)
                                        if not isinstance(a, (pd.DataFrame, pd.Series)) and not isinstance(b, (pd.DataFrame, pd.Series))
                                        else pd.DataFrame(
                                            np.maximum(a.values, b.values),
                                            index=a.index,
                                            columns=a.columns,
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ),
        },
        'bimin': {
            'symb': 'min',
            'latex': '\\min',
            'nop': 2,
            'func': lambda a, b: (
                (
                    pd.DataFrame(
                        np.minimum(a.values, CompositeExpr._df_series_broadcast(a, b)),
                        index=a.index,
                        columns=a.columns,
                    )
                    if isinstance(a, pd.DataFrame) and isinstance(b, pd.Series)
                    else (
                        pd.DataFrame(
                            np.minimum(CompositeExpr._df_series_broadcast(b, a), b.values),
                            index=b.index,
                            columns=b.columns,
                        )
                        if isinstance(a, pd.Series) and isinstance(b, pd.DataFrame)
                        else (
                            (lambda aa, bb: pd.Series(np.minimum(aa.values, bb.values), index=aa.index))(
                                *CompositeExpr._series_align(a, b)
                            )
                            if isinstance(a, pd.Series) and isinstance(b, pd.Series)
                            else (
                                a.clip(upper=b)  # type: ignore[arg-type]
                                if isinstance(a, pd.DataFrame) and np.isscalar(b)
                                else (
                                    b.clip(upper=a)  # type: ignore[arg-type]
                                    if isinstance(b, pd.DataFrame) and np.isscalar(a)
                                    else (
                                        np.minimum(a, b)
                                        if not isinstance(a, (pd.DataFrame, pd.Series)) and not isinstance(b, (pd.DataFrame, pd.Series))
                                        else pd.DataFrame(
                                            np.minimum(a.values, b.values),
                                            index=a.index,
                                            columns=a.columns,
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            ),
        },
    }

    _Ops = {
        'add': {'symb': '+', 'latex': '+', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "add")},
        'sub': {'symb': '-', 'latex': '-', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "sub")},
        'mul': {'symb': '*', 'latex': '\\times', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "mul")},
        'div': {'symb': '/', 'latex': '\\frac', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "div")},
        'gt': {'symb': '>', 'latex': '>', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "gt")},
        'lt': {'symb': '<', 'latex': '<', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "lt")},
        'ge': {'symb': '>=', 'latex': '\\ge', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "ge")},
        'le': {'symb': '<=', 'latex': '\\le', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "le")},
        'eq': {'symb': '==', 'latex': '=', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "eq")},
        'ne': {'symb': '!=', 'latex': '\\neq', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "ne")},
        'and': {'symb': '&', 'latex': '\\wedge', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "and")},
        'or': {'symb': '|', 'latex': '\\vee', 'nop': 2, 'func': lambda a, b, *args: CompositeExpr._binop(a, b, "or")},
        'neg': {'symb': '-', 'latex': '-', 'nop': 1, 'func': lambda a, *args: -a},
        'abs': {'symb': 'abs', 'latex': '\\mathrm{abs}', 'nop': 1, 'func': lambda a, *args: abs(a)},
        'not': {'symb': '~', 'latex': '\\neg', 'nop': 1, 'func': lambda a, *args: ~a},
        'log': {'symb': 'log', 'latex': '\\log', 'nop': 1, 'func': lambda a, *args: np.log(a)},
        'sign': {'symb': 'sign', 'latex': '\\mathrm{sign}', 'nop': 1, 'func': lambda a, *args: np.sign(a)},
        'sqrt': {'symb': 'sqrt', 'latex': '\\sqrt', 'nop': 1, 'func': lambda a, *args: np.sqrt(a)},
        'pow': {'symb': '**', 'latex': '^', 'nop': 2, 'func': lambda a, b, *args: a ** b},
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
        'neg': 70, 'abs': 70, 'not': 70, 'log': 70, 'sign': 70, 'sqrt': 70,
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
                return f"{self._Ops[self.op]['latex']}\\left({operand_latex}\\right)"
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
            'log': 'LOG', 'sign': 'SIGN', 'sqrt': 'SQRT',
            'bimax': 'MAX', 'bimin': 'MIN',
        }
        op_alias = op_aliases.get(self.op, self.op.upper())
        parts = [opnd._get_alias() for opnd in self.operands]
        return f"{op_alias}_{'_'.join(parts)}"


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
                mask = CompositeExpr._df_series_broadcast(a, cond).astype(bool)
                cond_df = pd.DataFrame(mask, index=a.index, columns=a.columns)
            else:
                cond_df = pd.DataFrame(bool(cond), index=a.index, columns=a.columns)

            if isinstance(b, pd.Series):
                b_arr = CompositeExpr._df_series_broadcast(a, b)
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

