from __future__ import annotations

from server.services.factor_registry import _build_factor_from_source


_FACTOR_SOURCE = """
from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef


class UserAlpha(FactorFamily):
    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.CLOSE)
"""


def test_public_factor_family_uses_common_prefix() -> None:
    family = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="$COMMON")

    assert family is not None
    assert family.name.startswith("$COMMON:UserAlpha:")


def test_user_factor_family_and_factor_use_username_prefix() -> None:
    family = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="18717974771")

    assert family is not None
    assert family.name.startswith("18717974771:UserAlpha:")
    factor = family.factor_from_alias("UserAlpha")
    assert factor.name.startswith("18717974771:UserAlpha")
