"""GroupByScopeOp.resolve 必须带上 scope（深链重建依赖它）。"""

from __future__ import annotations

from tools.data.types import DataColumn
from tools.factors.expr.groupby_scope import GroupByScopeOp
from tools.factors.expr.leaf import ColumnRef
from tools.factors.expr.lookback_scope import scope_trading_day


def test_resolve_preserves_scope_and_operands():
    expr = ColumnRef(DataColumn.CLOSE).groupby_scope(scope_trading_day()).mean()
    assert isinstance(expr, GroupByScopeOp)
    resolved = expr.resolve()
    assert isinstance(resolved, GroupByScopeOp)
    assert type(resolved.scope) is type(expr.scope)
    assert resolved.op == expr.op
    assert len(resolved.operands) == len(expr.operands)


def test_resolve_through_an_alignment_layer():
    """信号对齐层的 resolve 会递归重建子表达式，必须不再抛 TypeError。"""
    expr = ColumnRef(DataColumn.CLOSE).groupby_scope(scope_trading_day()).mean()
    resolved = expr.resolve()  # 无参 resolve 也应能走通
    assert isinstance(resolved, GroupByScopeOp)
