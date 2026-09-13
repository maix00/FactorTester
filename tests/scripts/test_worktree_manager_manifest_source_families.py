"""Verify manifest-only source families appear in the catalog listing.

Source bodies are never shipped over the account-domain outbox, so a family
whose manifest synced but whose local source body was not hydrated would
disappear from the public factor-library listing.  The listing only needs the
identity fields (family name + description), which the account-domain mirror
already carries.  These tests pin down that mirror fallback.
"""

from __future__ import annotations

import hashlib

from typing import Any

from server.manager.services.client_factor_catalog import (
    ClientFactorCatalogMixin,
)


# A stub account-domain synchronizer that reports the rows we pretend are in
# the local mirror.  ``entities`` is the only interface the mixin reads.
class _StubSynchronizer:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def entities(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return list(self._rows)


class _Stub(ClientFactorCatalogMixin):
    def __init__(self, synchronizer: Any):
        self.account_domain_sync = synchronizer
        self.local_account_store: Any = None

    def _account_catalog_entities(
        self, principal: str, **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return list(self.account_domain_sync.entities(principal, **kwargs))


def _mirror_row(
    factor_id: str,
    *,
    factor_name: str = "",
    owner: str = "alice",
    source_kind: str = "custom",
    fingerprint: str = "",
) -> dict[str, Any]:
    return {
        "deleted": 0,
        "payload": {
            "factor_id": factor_id,
            "factor_name": factor_name or factor_id,
            "owner_username": owner,
            "source_kind": source_kind,
            "family_formula_fingerprint": fingerprint,
        },
    }


def test_manifest_source_families_projects_mirror_rows() -> None:
    stub = _Stub(_StubSynchronizer([
        _mirror_row("SgChgPct", fingerprint="a" * 64),
        _mirror_row("RwHHV", owner="alice", fingerprint="b" * 64),
    ]))
    families = stub._manifest_source_families("alice")
    assert len(families) == 2
    aliases = {f["factor_family_alias"] for f in families}
    assert aliases == {"SgChgPct", "RwHHV"}
    by_alias = {f["factor_family_alias"]: f for f in families}
    assert by_alias["SgChgPct"]["factor_family_name"] == "SgChgPct"
    assert by_alias["SgChgPct"]["factor_kind"] == "custom"
    assert by_alias["SgChgPct"]["family_formula_fingerprint"] == "a" * 64


def test_manifest_source_families_skips_deleted_rows() -> None:
    row = _mirror_row("Gone", fingerprint="c" * 64)
    row["deleted"] = 1
    stub = _Stub(_StubSynchronizer([row]))
    families = stub._manifest_source_families("alice")
    assert families == []


def test_manifest_source_families_skips_non_dict_payload() -> None:
    stub = _Stub(_StubSynchronizer([{"deleted": 0, "payload": "not-a-dict"}]))
    families = stub._manifest_source_families("alice")
    assert families == []


def test_manifest_source_families_preserves_unresolved_identity() -> None:
    stub = _Stub(_StubSynchronizer([_mirror_row("VpTurnoverEntropy", owner="alice", fingerprint="")]))
    (family,) = stub._manifest_source_families("alice")
    assert family["family_formula_fingerprint"] == ""


def test_manifest_source_families_projects_through_build_projection() -> None:
    from server.modules.custom_factors.client_library import (
        build_client_library_projection,
    )

    stub = _Stub(_StubSynchronizer([
        _mirror_row("SgChgPct", owner="alice", fingerprint="a" * 64),
        _mirror_row("VpTurnoverEntropy", owner="alice", fingerprint=""),
    ]))
    families = stub._manifest_source_families("alice")
    projection = build_client_library_projection({
        "factors": [],
        "families": families,
        "errors": [],
    }, principal="alice")
    family_rows = projection.get("families") or []
    # Both families must survive the projection (no fingerprint-less drop).
    assert {f["factor_family_alias"] for f in family_rows} == {
        "SgChgPct", "VpTurnoverEntropy",
    }
    by_alias = {f["factor_family_alias"]: f for f in family_rows}
    assert by_alias["VpTurnoverEntropy"]["family_formula_fingerprint"] == ""
    assert by_alias["VpTurnoverEntropy"]["family_ref"] == ""
    assert by_alias["VpTurnoverEntropy"]["identity_status"] == "unresolved"


def test_merge_source_families_prefers_rich_row_over_manifest() -> None:
    rich = {
        "factor_family_alias": "SgChgPct",
        "factor_family_name": "SgChgPct",
        "owner_username": "alice",
        "description": "本地正文已有的说明",
        "factor_count": 3,
    }
    mirror = {
        "factor_family_alias": "SgChgPct",
        "factor_family_name": "SgChgPct",
        "owner_username": "alice",
        "description": "",
        "factor_count": 0,
    }
    merged = _Stub(None)._merge_source_families(
        [rich], [mirror],
    )
    assert len(merged) == 1
    assert merged[0]["description"] == "本地正文已有的说明"
    assert merged[0]["factor_count"] == 3


def test_merge_source_families_dedupes_but_keeps_distinct() -> None:
    a = {"factor_family_alias": "A", "owner_username": "alice"}
    b = {"factor_family_alias": "B", "owner_username": "alice"}
    c = {"factor_family_alias": "A", "owner_username": "bob"}
    merged = _Stub(None)._merge_source_families(
        [a, b], [c],
    )
    # A/alice, B/alice, A/bob are three distinct identities
    assert len(merged) == 3


def test_failed_local_source_does_not_mask_valid_manifest():
    stub = _Stub(_StubSynchronizer([]))
    failed = {"factor_family_alias": "F", "owner_username": "alice", "family_formula_fingerprint": ""}
    valid = {**failed, "family_formula_fingerprint": "a" * 64}
    assert stub._merge_source_families([failed], [valid]) == [valid]


def test_factor_library_passes_account_alias_to_manifest_templates(monkeypatch, tmp_path):
    import settings
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    monkeypatch.setattr(settings, 'CACHE_DB_PATH', tmp_path / 'catalog.sqlite')
    LocalAccountDomainStore(settings.CACHE_DB_PATH)
    principal = 'GTHT@MaxJJW@392452984564'
    stub = _Stub(_StubSynchronizer([_mirror_row('Mm', owner=principal)]))
    stub._refresh_account_domain_async = lambda *_: None
    stub._local_account = lambda _: {'username': principal, 'alias': '新别名'}
    stub._custom_source_families = lambda *_: []
    stub._registered_factor_rows = lambda *_: []
    family = stub.factor_library(principal)['families'][0]
    assert family['owner_alias'] == '新别名'
    assert family['owner_username'] == principal
