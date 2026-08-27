from __future__ import annotations

import pytest

from server.services import factor_source_catalog
from server.services.factor_source_catalog import FactorSourceCatalog


def _detail(_source: str, _factor_id: str, _metadata: dict) -> dict:
    return {
        "source_code": "source",
        "family_formula_fingerprint": "a" * 64,
        "params": [],
    }


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
