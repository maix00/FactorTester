from __future__ import annotations

import pytest

from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef, ConstExpr
from tools.parameters import DataColumnParam, FactorParam, WindowParam


class _AliasFamily(FactorFamily):
    @staticmethod
    def factor_expr():
        window = WindowParam("AliasWindow", default_value="1d")
        return ColumnRef(DataColumn.CLOSE).rolling(window).mean()


class _NestedAliasFamily(FactorFamily):
    @staticmethod
    def factor_expr():
        nested = FactorParam("NestedFactor", default_value=None)
        return nested + ColumnRef(DataColumn.CLOSE)


class _ColumnAliasFamily(FactorFamily):
    @staticmethod
    def factor_expr():
        column = DataColumnParam("P", default_value="CA")
        return column + 1


class _ConstantFactorParamFamily(FactorFamily):
    @staticmethod
    def factor_expr():
        threshold = FactorParam("Threshold", default_value=0.001)
        return ColumnRef(DataColumn.CLOSE) > threshold


def test_factor_family_parses_alias_and_creates_one_off_factor() -> None:
    family = _AliasFamily()
    alias = f"{family.alias}|AliasWindow:2m|$F:1m|$Rev"

    params = family.parse_alias(alias)
    factor = family.factor_from_alias(alias)

    assert params["AliasWindow"].isoformat() == "P0DT0H2M0S"
    assert params["$F"].isoformat() == "P0DT0H1M0S"
    assert params["$Rev"] is True
    assert factor.alias == alias


def test_factor_family_parser_preserves_nested_factor_alias_pipes() -> None:
    family = _NestedAliasFamily()
    alias = f"{family.alias}|NestedFactor:[Child|N:2m|$Rev]|$F:1d"

    assert family.parse_alias(alias)["NestedFactor"] == "Child|N:2m|$Rev"


def test_factor_family_numeric_factor_param_alias_round_trips() -> None:
    family = _ConstantFactorParamFamily()
    alias = family.get_alias(Threshold=0.025)

    parsed = family.parse_alias(alias)

    assert alias.endswith("|Threshold:[0.025]")
    assert isinstance(parsed["Threshold"], ConstExpr)
    assert parsed["Threshold"].value == 0.025


def test_factor_family_parser_accepts_frozen_legacy_column_brackets() -> None:
    family = _ColumnAliasFamily()

    params = family.parse_alias(f"{family.alias}|P:[CA]")

    assert params["P"] == DataColumn.CLOSE_ADJUSTED
    assert family.get_alias(**params) == f"{family.alias}|P:CA"


@pytest.mark.parametrize("alias", [
    "Other|AliasWindow:2m",
    "_AliasFamily|Unknown:2m",
    "_AliasFamily|AliasWindow:2m|AliasWindow:3m",
    "_AliasFamily|$Rev:0",
])
def test_factor_family_rejects_wrong_or_noncanonical_alias(alias: str) -> None:
    with pytest.raises(ValueError):
        _AliasFamily().parse_alias(alias)


def test_factor_family_rejects_legacy_positional_alias() -> None:
    family = _AliasFamily()

    with pytest.raises(ValueError):
        family.parse_alias(f"{family.alias}:0")

    assert family.get_alias(AliasWindow="2m").endswith("|AliasWindow:2m")
