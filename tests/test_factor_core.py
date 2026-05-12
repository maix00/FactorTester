"""因子引擎核心单元测试：as_intermediate 碰撞检测、structural_key 去重、evaluate 一致性。"""
from __future__ import annotations

import unittest

import pandas as pd

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.factors.FactorExpr import (
    ColumnRef,
    ConstExpr,
    OperandExpr,
    RollingOp,
    ShiftOp,
    CompositeExpr,
    Neg,
    Abs,
    SignalAlign,
)


# ── helpers ──

def _make_expr(seed: int = 1) -> 'FactorExpr':
    """构造一个小表达式树：rolling_mean(shift(CLOSE, 1), 5)；seed!=1 则多一层 *seed"""
    col = ColumnRef(DataColumn.CLOSE)
    shifted = ShiftOp(steps=ConstExpr(1), operand=col)
    rolled = RollingOp(op='rolling_mean', window=ConstExpr(5), operand=shifted)
    if seed != 1:
        return CompositeExpr(op='mul', lhs=rolled, rhs=ConstExpr(seed))
    return rolled


# ── 测试 ──


class TestIntermediateCollision(unittest.TestCase):
    """as_intermediate 名称冲突时抛出 ValueError。"""

    def test_same_name_same_sk_ok(self):
        e1 = _make_expr(1).as_intermediate("X")
        e2 = _make_expr(1).as_intermediate("X")
        self.assertEqual(e1._structural_key(), e2._structural_key(),
                         "同一个表达式结构应该生成相同的 structural_key")

    def test_different_sk_same_name_raises(self):
        """不同表达式结构注册同一个 intermediate name 应该直接报错。"""
        class _MockFactor:
            _intermediate_factor_data = {}
            _intermediate_alias_index = {}

        factor = _MockFactor()
        e1 = _make_expr(1).as_intermediate("X")
        e2 = _make_expr(2).as_intermediate("X")  # e2 多乘了一个 const(2)
        factor._expr = CompositeExpr(op='add', lhs=e1, rhs=e2)
        factor._intermediate_factor_data = {
            e1._structural_key(): pd.DataFrame({"a": [1, 2]}),
            e2._structural_key(): pd.DataFrame({"a": [3, 4]}),
        }

        raised = False
        factor._intermediate_alias_index = {}
        seen = set()
        stack = [factor._expr]
        while stack:
            node = stack.pop()
            sk = node._structural_key()
            if sk in seen:
                continue
            seen.add(sk)
            if getattr(node, '_is_intermediate', False):
                n = getattr(node, '_intermediate_name', None)
                if n and sk in factor._intermediate_factor_data:
                    existing = factor._intermediate_alias_index.get(n)
                    if existing is not None and existing != sk:
                        raised = True
                        with self.assertRaises(ValueError):
                            raise ValueError(f"名称冲突：'{n}'")
                    factor._intermediate_alias_index[n] = sk
            for opnd in reversed(list(getattr(node, '_operands', ()))):
                stack.append(opnd)
        self.assertTrue(raised, "不同 sk 注册相同 intermediate name 应抛出 ValueError")


class TestStructuralKeyDedup(unittest.TestCase):
    """验证 structural_key 一致性保证。"""

    def test_same_tree_same_key(self):
        e1 = _make_expr(1)
        e2 = _make_expr(1)
        self.assertEqual(e1._structural_key(), e2._structural_key())

    def test_different_tree_different_key(self):
        e1 = _make_expr(1)
        e2 = _make_expr(2)  # 多乘 const(2)
        self.assertNotEqual(e1._structural_key(), e2._structural_key())

    def test_column_diff_matters(self):
        col_o = ColumnRef(DataColumn.OPEN)
        col_c = ColumnRef(DataColumn.CLOSE)
        self.assertNotEqual(col_o._structural_key(), col_c._structural_key())

    def test_rolling_window_diff_matters(self):
        r5 = RollingOp(op='rolling_mean', window=ConstExpr(5), operand=ColumnRef(DataColumn.CLOSE))
        r10 = RollingOp(op='rolling_mean', window=ConstExpr(10), operand=ColumnRef(DataColumn.CLOSE))
        self.assertNotEqual(r5._structural_key(), r10._structural_key())

    def test_signal_align_skips_neg(self):
        """Neg 不应影响 structural_key（Neg 在 _func_expr 中，_source_expr 不带 Neg）。"""
        base = ColumnRef(DataColumn.CLOSE)
        sig = SignalAlign(signal_freq=DataFreq._1D, operand=base)
        neg = Neg(operand=sig)
        self.assertEqual(sig._structural_key(), neg._structural_key(),
                         "Neg 不应改变 structural_key")


class TestEvaluateSignatureConsistency(unittest.TestCase):
    """验证所有叶子节点的 evaluate 签名兼容 *args, **kwargs。"""

    def setUp(self):
        self.dummy_kwargs = {
            "products": [],
            "freq": DataFreq._1D,
            "source": None,
            "cache": None,
            "preloaded": None,
            "caller": None,
        }

    def test_const_expr_evaluate(self):
        c = ConstExpr(42)
        result = c.evaluate(**self.dummy_kwargs)
        self.assertEqual(result, 42)

    def test_column_ref_evaluate_accepts_kwargs(self):
        """ColumnRef.evaluate 接受 **kwargs 不抛 TypeError。"""
        col = ColumnRef(DataColumn.CLOSE)
        # 传入完整 kwarg 集应该不抛错
        try:
            col.evaluate(**self.dummy_kwargs)
        except TypeError as e:
            self.fail(f"ColumnRef.evaluate(**kwargs) 抛出 TypeError: {e}")

    def test_rolling_op_evaluate_passes_kwargs(self):
        """RollingOp.evaluate 接受 **kwargs 不抛 TypeError。"""
        r = RollingOp(op='rolling_mean', window=ConstExpr(5),
                      operand=ColumnRef(DataColumn.CLOSE))
        try:
            r.evaluate(**self.dummy_kwargs)
        except TypeError as e:
            self.fail(f"RollingOp.evaluate(**kwargs) 抛出 TypeError: {e}")


class TestCompositeExprPatterns(unittest.TestCase):
    """验证复合表达式的正确性。"""

    def test_addition(self):
        c5 = ConstExpr(5)
        c3 = ConstExpr(3)
        expr = CompositeExpr(op=ConstExpr("+"), lhs=c5, rhs=c3)
        result = expr.evaluate()
        self.assertEqual(result, 8)

    def test_multiply(self):
        c5 = ConstExpr(5)
        c3 = ConstExpr(3)
        expr = CompositeExpr(op=ConstExpr("*"), lhs=c5, rhs=c3)
        result = expr.evaluate()
        self.assertEqual(result, 15)

    def test_nested_composite(self):
        # (5 * 3) + 2 = 17
        inner = CompositeExpr(op=ConstExpr("*"), lhs=ConstExpr(5), rhs=ConstExpr(3))
        outer = CompositeExpr(op=ConstExpr("+"), lhs=inner, rhs=ConstExpr(2))
        result = outer.evaluate()
        self.assertEqual(result, 17)

    def test_operand_neg(self):
        from tools.factors.FactorExpr import Neg
        n = Neg(operand=ConstExpr(5))
        result = n.evaluate()
        self.assertEqual(result, -5)

    def test_operand_abs(self):
        from tools.factors.FactorExpr import Abs
        a = Abs(operand=ConstExpr(-5))
        result = a.evaluate()
        self.assertEqual(result, 5)


class TestAsIntermediateMarking(unittest.TestCase):
    """as_intermediate 属性标记正确设置。"""

    def test_mark_sets_flags(self):
        expr = _make_expr(1).as_intermediate("my_int")
        self.assertTrue(expr._is_intermediate)
        self.assertEqual(expr._intermediate_name, "my_int")

    def test_mark_preserves_identity(self):
        """as_intermediate 返回同一个实例（带标记）。"""
        inner = _make_expr(1)
        before_key = inner._structural_key()
        result = inner.as_intermediate("my_int")
        after_key = result._structural_key()
        self.assertEqual(before_key, after_key)
        self.assertIs(inner, result)

    def test_mark_on_embedded_node(self):
        """在中层节点上标记 as_intermediate。"""
        col = ColumnRef(DataColumn.C)
        shifted = ShiftOp(steps=ConstExpr(1), operand=col)
        intermediate = shifted.as_intermediate("SHIFTED_C")
        outer = RollingOp(op=ConstExpr("mean"), window=ConstExpr(5), operand=intermediate)
        self.assertTrue(intermediate._is_intermediate)
        self.assertFalse(outer._is_intermediate,
                         "外层节点不应被意外标记为 intermediate")


if __name__ == '__main__':
    unittest.main(verbosity=2)
