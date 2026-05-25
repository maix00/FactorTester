from __future__ import annotations

import pandas as pd

from tools.data.DataColumn import DataColumn
from tools.factors.FactorExpr import ColumnRef, CompositeExpr, ConstExpr, RollingOp, ShiftOp


def _expr(seed: int = 1):
    base = ColumnRef(DataColumn.CLOSE)
    shifted = ShiftOp("shift", ConstExpr(1), base)
    rolled = RollingOp("rolling_mean", ConstExpr(5), shifted)
    return rolled if seed == 1 else CompositeExpr("mul", rolled, ConstExpr(seed))


def test_structural_key_is_stable_for_equivalent_trees():
    assert _expr()._structural_key() == _expr()._structural_key()


def test_structural_key_changes_when_formula_changes():
    assert _expr()._structural_key() != _expr(seed=2)._structural_key()


def test_tree_repr_shows_nested_branch_connectors():
    expr = CompositeExpr(
        "mul",
        CompositeExpr(
            "sub",
            ColumnRef(DataColumn.CLOSE),
            ColumnRef(DataColumn.OPEN),
        ),
        ColumnRef(DataColumn.VOLUME),
    )

    assert expr.tree_repr() == (
        "mul\n"
        "├─ sub\n"
        "│  ├─ ColumnRef[CLOSE]\n"
        "│  └─ ColumnRef[OPEN]\n"
        "└─ ColumnRef[VOLUME]"
    )


def test_intermediate_name_collision_is_detectable():
    class MockFactor:
        _intermediate_factor_data = {}
        _intermediate_alias_index = {}

    e1 = _expr().as_intermediate("X")
    e2 = _expr(seed=2).as_intermediate("X")
    factor = MockFactor()
    factor._intermediate_factor_data = {
        e1._structural_key(): pd.DataFrame({"a": [1.0]}),
        e2._structural_key(): pd.DataFrame({"a": [2.0]}),
    }

    factor._intermediate_alias_index["X"] = e1._structural_key()
    existing = factor._intermediate_alias_index["X"]
    assert existing != e2._structural_key()
