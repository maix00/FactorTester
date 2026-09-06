from __future__ import annotations

import pytest

from server.services import factor_source_catalog
from server.services.factor_source_catalog import FactorSourceCatalog
from tools.data.account_manage import can_view_user_scope


def test_can_view_user_scope_own_scope_survives_empty_catalog(
    monkeypatch,
) -> None:
    """One's own scope is visible even when the account store is empty."""
    monkeypatch.setattr(
        "tools.data.account_manage.visible_usernames_for",
        lambda *_args, **_kwargs: [],
    )
    assert can_view_user_scope("user@one", "user@one") is True
    assert can_view_user_scope("user@one", "user@two") is False
    assert can_view_user_scope(None, None) is False


def _detail(_source: str, _factor_id: str, _metadata: dict) -> dict:
    return {
        "source_code": "source",
        "family_formula_fingerprint": "a" * 64,
        "params": [],
    }


def test_historical_version_does_not_need_current_body_or_display_metadata(monkeypatch):
    def unavailable(*args):
        raise factor_source_catalog.FactorSourceMetadataUnavailable('cold peer')
    monkeypatch.setattr(factor_source_catalog, 'load_factor_source', unavailable)
    monkeypatch.setattr(factor_source_catalog, 'get_factor_source_metadata', unavailable)
    monkeypatch.setattr(factor_source_catalog, 'load_factor_formula_version', lambda *args:{'source_code':'source'})
    monkeypatch.setattr(FactorSourceCatalog, '_detail', staticmethod(_detail))
    assert FactorSourceCatalog().version('alice','custom','History','a'*64)['success']
    monkeypatch.setattr(factor_source_catalog, 'can_view_user_scope', lambda *args:False)
    with pytest.raises(PermissionError):
        FactorSourceCatalog().version('bob','custom','History','a'*64,owner_username='alice')


def test_custom_source_versions_enforce_scope_and_bound_limit(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        factor_source_catalog, "can_view_user_scope",
        lambda principal, owner: (principal, owner) == ("parent", "child"),
    )
    monkeypatch.setattr(
        factor_source_catalog, "load_factor_source",
        lambda owner, factor_id: "source"
        if (owner, factor_id) == ("child", "Momentum") else None,
    )
    monkeypatch.setattr(
        factor_source_catalog, "get_factor_source_metadata", lambda *_args: {},
    )
    monkeypatch.setattr(FactorSourceCatalog, "_detail", staticmethod(_detail))
    monkeypatch.setattr(
        factor_source_catalog, "list_factor_formula_versions",
        lambda *args, **kwargs: calls.append((args, kwargs)) or [],
    )

    value = FactorSourceCatalog().versions(
        "parent", "custom", "Momentum",
        owner_username="child", limit=9999,
    )

    assert value["factor_owner_ref"] == "child"
    assert value["current_fingerprint"] == "a" * 64
    assert calls[0][1]["limit"] == 500


def test_custom_source_rejects_unreadable_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_source_catalog, "can_view_user_scope", lambda *_args: False,
    )

    with pytest.raises(PermissionError):
        FactorSourceCatalog().version(
            "reader", "custom", "Secret", "current",
            owner_username="owner",
        )


def test_custom_source_own_owner_reads_even_when_scope_catalog_fails(
    monkeypatch,
) -> None:
    """A principal must never be locked out of its own source.

    The account catalog may transiently fail (control-db fallback to an empty
    local store) and answer ``False`` for every pair — saving a factor whose
    frozen FactorParam dependency points back at the same user surfaced
    ``PermissionError: 无权查看该用户因子源码``.  Own-source reads need no
    cross-account grant and must bypass the catalog.
    """
    monkeypatch.setattr(
        factor_source_catalog, "can_view_user_scope", lambda *_args: False,
    )
    loaded = []
    monkeypatch.setattr(
        factor_source_catalog, "load_factor_source",
        lambda owner, factor_id: loaded.append((owner, factor_id)) or "own-source",
    )
    monkeypatch.setattr(
        factor_source_catalog, "get_factor_source_metadata", lambda *_args: {},
    )
    monkeypatch.setattr(
        FactorSourceCatalog, "_detail",
        staticmethod(lambda *_args: {"source_code": "own-source", "params": []}),
    )

    value = FactorSourceCatalog().version(
        "GTHT@MaxJJW@392452984564", "custom", "SgChgPct", "current",
        owner_username="GTHT@MaxJJW@392452984564",
    )

    assert loaded == [("GTHT@MaxJJW@392452984564", "SgChgPct")]
    assert value["source_code"] == "own-source"


def test_historical_source_does_not_require_current_copy(monkeypatch) -> None:
    fingerprint = "b" * 64
    monkeypatch.setattr(
        factor_source_catalog, "load_public_factor_source", lambda _factor_id: None,
    )
    monkeypatch.setattr(
        factor_source_catalog, "get_factor_source_metadata", lambda *_args: {},
    )
    monkeypatch.setattr(
        factor_source_catalog, "load_factor_formula_version",
        lambda *_args: {
            "source_code": "historical",
            "family_formula_fingerprint": fingerprint,
        },
    )
    monkeypatch.setattr(
        FactorSourceCatalog,
        "_detail",
        staticmethod(lambda *_args: {"source_code": "historical", "params": []}),
    )

    value = FactorSourceCatalog().version(
        "reader", "public", "Momentum", fingerprint,
    )

    assert value["source_code"] == "historical"
    assert value["factor_owner_ref"] == "__public_jobs__"


def test_current_source_reports_missing_copy(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_source_catalog, "load_public_factor_source", lambda _factor_id: None,
    )

    with pytest.raises(FileNotFoundError):
        FactorSourceCatalog().version(
            "reader", "public", "Momentum", "current",
        )
