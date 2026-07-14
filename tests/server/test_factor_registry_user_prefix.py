from __future__ import annotations

import pytest

from server.services import factor_registry
from server.services.factor_registry import _build_factor_from_source, factor_from_alias, get_factor_family_instance


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


def test_owner_qualified_user_factor_alias_creates_one_off_factor(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: _FACTOR_SOURCE if (username, factor_id) == ("18717974771", "UserAlpha") else None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("18717974771:UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("18717974771:UserAlpha")


def test_unqualified_custom_factor_alias_uses_current_users_factor_library(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: _FACTOR_SOURCE if (username, factor_id) == ("18717974771", "UserAlpha") else None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("18717974771:UserAlpha")


def test_public_factor_alias_uses_common_prefix(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: _FACTOR_SOURCE if factor_id == "UserAlpha" else None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("$COMMON:UserAlpha")


def test_factor_family_rejects_other_users_custom_factor(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    with pytest.raises(PermissionError):
        get_factor_family_instance("18800000000:UserAlpha", username="18717974771")


def test_page_cache_is_not_factor_family_existence_authority(monkeypatch) -> None:
    stale = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="18717974771")
    factor_registry.page_families["page-1"] = {"18717974771:UserAlpha": stale}
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    with pytest.raises(ImportError, match="custom factor library"):
        get_factor_family_instance("UserAlpha", username="18717974771", page_uuid="page-1")

    factor_registry.page_families.pop("page-1", None)
