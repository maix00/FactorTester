"""Compact, source-free facts derived from one FactorExpr tree."""

from __future__ import annotations

from tools.data.types import DataColumn
from tools.factors.FactorExpr import ColumnRef, FactorExpr


def fixed_column_refs(expr: FactorExpr | None) -> list[str]:
    """Return distinct fixed ColumnRef values in first-appearance order."""
    if expr is None:
        return []
    values: list[str] = []
    seen_values: set[str] = set()
    seen_nodes: set[int] = set()
    stack = [expr]
    while stack:
        node = stack.pop()
        marker = id(node)
        if marker in seen_nodes:
            continue
        seen_nodes.add(marker)
        if isinstance(node, ColumnRef):
            value = (
                node.column.value
                if isinstance(node.column, DataColumn)
                else str(node.column)
            )
            if value not in seen_values:
                seen_values.add(value)
                values.append(value)
            continue
        children = [
            child
            for child in getattr(node, "_operands", ())
            if isinstance(child, FactorExpr)
        ]
        stack.extend(reversed(children))
    return values
