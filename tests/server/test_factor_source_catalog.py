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


def test_historical_version_does_not_need_current_body_or_display_metadata(monkeypatch):
    def unavailable(*args):
        raise factor_source_catalog.FactorSourceMetadataUnavailable('cold peer')
    monkeypatch.setattr(factor_source_catalog, 'load_factor_source', unavailable)
    monkeypatch.setattr(factor_source_catalog, 'get_factor_source_metadata', unavailable)
    monkeypatch.setattr(factor_source_catalog, 'load_factor_formula_version', lambda *args:{'source_code':'source'})
    monkeypatch.setattr(FactorSourceCatalog, '_detail', staticmethod(_detail))
    assert FactorSourceCatalog().version('alice','custom','History','a'*64)['success']


def test_custom_source_catalog_reads_metadata_and_bounds_limit(monkeypatch) -> None:
    calls = []
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


def test_storage_catalog_does_not_use_local_account_permissions() -> None:
    assert not hasattr(factor_source_catalog, "can_view_user_scope")


def test_custom_source_reads_only_after_http_keycloak_boundary(
    monkeypatch,
) -> None:
    """The adapter locates bytes; its HTTP callers enforce Keycloak grants."""
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
