from __future__ import annotations

import sqlite3

import pytest

from server.services import factor_registry
from server.services.factor_registry import (
    _build_factor_from_source,
    factor_from_alias,
    get_factor_family_instance,
)

_FACTOR_SOURCE = """
from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef


class UserAlpha(FactorFamily):
    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.CLOSE)
"""


def test_public_factor_family_uses_canonical_owner() -> None:
    family = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="$COMMON")

    assert family is not None
    assert family.name.startswith("runtime-factor-family:public:UserAlpha:")
    assert family.owner_ref == "public"
    assert "$COMMON" not in family.name


def test_user_factor_family_and_factor_use_username_prefix() -> None:
    family = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="18717974771")

    assert family is not None
    assert family.name.startswith(
        "runtime-factor-family:18717974771:UserAlpha:"
    )
    assert family.owner_ref == "18717974771"
    factor = family.factor_from_alias("UserAlpha")
    assert factor.name.startswith("runtime-factor:18717974771:UserAlpha")
    assert factor.owner_ref == "18717974771"


def test_owner_qualified_user_factor_alias_creates_one_off_factor(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: _FACTOR_SOURCE if (username, factor_id) == ("18717974771", "UserAlpha") else None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("18717974771:UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("runtime-factor:18717974771:UserAlpha")
    assert factor.owner_ref == "18717974771"


def test_unqualified_custom_factor_alias_uses_current_users_factor_library(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: _FACTOR_SOURCE if (username, factor_id) == ("18717974771", "UserAlpha") else None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("runtime-factor:18717974771:UserAlpha")
    assert factor.owner_ref == "18717974771"


def test_public_factor_alias_uses_canonical_owner(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: _FACTOR_SOURCE if factor_id == "UserAlpha" else None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias("UserAlpha", username="18717974771")

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("runtime-factor:public:UserAlpha")
    assert factor.owner_ref == "public"
    assert "$COMMON" not in factor.name


def test_factor_family_rejects_other_users_custom_factor(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    with pytest.raises(PermissionError):
        get_factor_family_instance("18800000000:UserAlpha", username="18717974771")


def test_visible_but_unregistered_other_user_factor_remains_private(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "factor-sharing.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE account_factor_param_configs (
                username TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                ff_alias TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (username, scope_key, ff_alias)
            )
            """
        )
    monkeypatch.setattr(factor_registry.Settings, "CACHE_DB_PATH", db_path)
    monkeypatch.setattr(
        factor_registry,
        "can_view_user_scope",
        lambda current, owner: (current, owner) == ("MaxA", "18717974771"),
        raising=False,
    )
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    with pytest.raises(ImportError, match="factor family source"):
        get_factor_family_instance("18717974771:UserAlpha", username="MaxA")


def test_visible_registered_other_user_factor_is_executable_with_owner_identity(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "factor-sharing.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE account_factor_param_configs (
                username TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                ff_alias TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (username, scope_key, ff_alias)
            );
            INSERT INTO account_factor_param_configs VALUES (
                '18717974771',
                'default',
                'UserAlpha',
                '{}',
                1.0
            );
            """
        )
    monkeypatch.setattr(factor_registry.Settings, "CACHE_DB_PATH", db_path)
    monkeypatch.setattr(
        factor_registry,
        "can_view_user_scope",
        lambda current, owner: (current, owner) == ("MaxA", "18717974771"),
        raising=False,
    )
    monkeypatch.setattr(
        factor_registry,
        "load_factor_source",
        lambda username, factor_id: (
            _FACTOR_SOURCE
            if (username, factor_id) == ("18717974771", "UserAlpha")
            else None
        ),
    )
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    factor = factor_from_alias(
        "18717974771:UserAlpha",
        username="MaxA",
    )

    assert factor.alias.startswith("UserAlpha")
    assert factor.name.startswith("runtime-factor:18717974771:UserAlpha")
    assert factor.owner_ref == "18717974771"


def test_visible_hydrated_other_user_factor_is_executable_before_library_sync(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "factor-sharing.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE account_factor_param_configs (
                username TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                ff_alias TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (username, scope_key, ff_alias)
            )
            """
        )
    monkeypatch.setattr(factor_registry.Settings, "CACHE_DB_PATH", db_path)
    monkeypatch.setattr(
        factor_registry,
        "can_view_user_scope",
        lambda current, owner: (current, owner) == ("MaxA", "18717974771"),
        raising=False,
    )
    monkeypatch.setattr(
        factor_registry,
        "load_factor_source",
        lambda username, factor_id: (
            _FACTOR_SOURCE
            if (username, factor_id) == ("18717974771", "UserAlpha")
            else None
        ),
    )
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    source = factor_registry.resolve_factor_family_source(
        "18717974771:UserAlpha",
        username="MaxA",
    )

    assert source["canonical_family_ref"] == "18717974771:UserAlpha"
    assert source["source_code"] == _FACTOR_SOURCE


def test_manager_authorized_direct_child_source_is_executable(
    monkeypatch,
    tmp_path,
) -> None:
    db_path = tmp_path / "factor-sharing.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE account_factor_param_configs (
                username TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                ff_alias TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (username, scope_key, ff_alias)
            )
            """
        )
    monkeypatch.setattr(factor_registry.Settings, "CACHE_DB_PATH", db_path)
    monkeypatch.setattr(factor_registry, "can_view_user_scope", lambda *_: False)
    monkeypatch.setattr(
        factor_registry,
        "load_factor_source",
        lambda username, factor_id: (
            _FACTOR_SOURCE
            if (username, factor_id) == ("child", "UserAlpha")
            else None
        ),
    )

    with factor_registry.authorized_factor_source_owners(["parent", "child"]):
        source = factor_registry.resolve_factor_family_source(
            "child:UserAlpha", username="parent",
        )

    assert source["canonical_family_ref"] == "child:UserAlpha"


def test_manager_authorization_does_not_include_unlisted_owner(monkeypatch) -> None:
    monkeypatch.setattr(factor_registry, "can_view_user_scope", lambda *_: False)

    with (
        factor_registry.authorized_factor_source_owners(["parent", "child"]),
        pytest.raises(PermissionError, match="not accessible"),
    ):
        factor_registry.resolve_factor_family_source(
            "grandchild:UserAlpha", username="parent",
        )


def test_namespaced_owner_reference_is_not_truncated() -> None:
    assert factor_registry._split_factor_owner_ref(
        "profile:maxa:UserAlpha"
    ) == ("profile:maxa", "UserAlpha")

    with pytest.raises(ValueError, match="owner reference"):
        factor_registry._split_factor_owner_ref("profile:maxa")


def test_public_family_source_uses_canonical_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda factor_id: _FACTOR_SOURCE if factor_id == "UserAlpha" else None,
    )

    source = factor_registry.resolve_factor_family_source(
        "public:UserAlpha",
        username="18717974771",
    )

    assert source["canonical_family_ref"] == "public:UserAlpha"
    assert source["source_owner"] == "public"


def test_page_cache_is_not_factor_family_existence_authority(monkeypatch) -> None:
    stale = _build_factor_from_source("UserAlpha", _FACTOR_SOURCE, user_prefix="18717974771")
    factor_registry.page_families["page-1"] = {"18717974771:UserAlpha": stale}
    monkeypatch.setattr(factor_registry, "load_factor_source", lambda username, factor_id: None)
    monkeypatch.setattr(factor_registry, "load_public_factor_source", lambda factor_id: None)
    monkeypatch.setattr(factor_registry.os.path, "isfile", lambda path: False)

    with pytest.raises(ImportError, match="custom factor library"):
        get_factor_family_instance("UserAlpha", username="18717974771", page_uuid="page-1")

    factor_registry.page_families.pop("page-1", None)
