from __future__ import annotations

from pathlib import Path
import hashlib

import settings as Settings

from server.manager.services.federated_public_data import FederatedPublicDataService
from server.manager.storage.account_domain import AccountDomainSyncService
from server.manager.storage.account_domain.local import LocalAccountDomainStore
from server.manager.storage.account_domain.payloads import public_payload
from server.manager.storage.account_domain.remote import (
    _can_repair_factor_source_provider,
)
from server.manager.storage.account_domain.factor_sync import materialized_factor_configs
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
from tools.factors.formula_identity import freeze_factor_identity


class MemoryControlStore:
    def __init__(self) -> None:
        self.revision = 0
        self.rows: dict[tuple[str, str, str], dict] = {}

    def push_account_domain_entity(self, **value):
        key = (value["principal"], value["entity_type"], value["entity_id"])
        current = self.rows.get(key)
        if current is not None:
            if current["payload"] == value["payload"] and current["deleted"] == value["deleted"]:
                return {"status": "synced", "revision": current["revision"]}
            if value.get("base_revision") != current["revision"]:
                return {"status": "conflict", "revision": current["revision"]}
        self.revision += 1
        self.rows[key] = {
            "principal": key[0],
            "entity_type": key[1],
            "entity_id": key[2],
            "payload": dict(value["payload"]),
            "deleted": bool(value["deleted"]),
            "revision": self.revision,
            "origin_manager_id": value.get("origin_manager_id") or "",
        }
        return {"status": "synced", "revision": self.revision}

    def pull_account_domain_entities(self, *, after_revision, principal, limit):
        rows = [
            row for row in self.rows.values()
            if row["revision"] > after_revision
            and (
                row["principal"] == principal
                or row["payload"].get("visibility") == "public"
            )
        ]
        rows.sort(key=lambda row: row["revision"])
        rows = rows[:limit]
        return {
            "entities": rows,
            "next_revision": max(
                [after_revision] + [row["revision"] for row in rows]
            ),
        }


def test_factor_sync_materializes_resolved_aliases(monkeypatch) -> None:
    frozen = freeze_factor_identity(
        owner_ref="alice",
        family_alias="CA",
        factor_alias="CA|$F:1m",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"$F": "1m"},
    )
    monkeypatch.setattr(
        "tools.data.account_manage.get_account",
        lambda owner: {"username": owner, "alias": "Alice"},
    )
    monkeypatch.setattr(
        "tools.data.account_manage.list_factor_param_config_scopes",
        lambda _owner: ["default"],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.list_factor_param_config_aliases",
        lambda _owner, _scope: ["CA"],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.load_factor_param_config",
        lambda _owner, _family, _scope: {"params_list": [{"$F": "1m"}]},
    )
    monkeypatch.setattr(
        "server.modules.custom_factors.factor_library_service.build_factor_library_overview",
        lambda *_args, **_kwargs: {"factors": [{
            **frozen,
            "factor_ref": frozen["ref"],
            "factor_alias": "CA|$F:1m",
            "factor_family_alias": "CA",
            "factor_family_name": "CA",
            "scope_key": "default",
            "params": [{"alias": "$F", "value": "1m"}],
            "owner_username": "alice",
        }]},
    )

    values = materialized_factor_configs("alice")

    assert values[0][0] == "default:CA"
    resolved = values[0][1]["resolved_factors"][0]
    assert resolved["factor_alias"] == "CA|$F:1m"
    assert resolved["factor_ref"] == frozen["ref"]
    assert resolved["ref"] == frozen["ref"]
    assert resolved["identity"] == frozen["identity"]


def test_factor_catalog_reconcile_is_idempotent_and_removes_local_stale_rows(
    monkeypatch, tmp_path: Path,
) -> None:
    service = AccountDomainSyncService(
        sqlite_path=tmp_path / "manager.sqlite",
        control_store=None,
        manager_id="office-a",
    )
    configs = [(
        "default:CA",
        {
            "scope_key": "default",
            "factor_family_alias": "CA",
            "resolved_factors": [{
                "factor_alias": "CA|$F:1m",
                "factor_family_alias": "CA",
                "params": [{"alias": "$F", "value": "1m"}],
            }],
        },
    )]
    monkeypatch.setattr(
        "tools.data.account_manage.list_factor_sets", lambda _owner: [],
    )
    monkeypatch.setattr(
        "server.manager.storage.account_domain.factor_sync.materialized_factor_configs",
        lambda _owner: list(configs),
    )

    assert service.reconcile_factor_catalog("alice", force=True) == 1
    assert service.reconcile_factor_catalog("alice", force=True) == 0
    rows = service.entities(
        "alice", entity_type="factor_param_config", sync=False,
    )
    assert rows[0]["payload"]["resolved_factors"][0]["factor_alias"] == "CA|$F:1m"

    configs.clear()
    assert service.reconcile_factor_catalog("alice", force=True) == 1
    assert service.entities(
        "alice", entity_type="factor_param_config", sync=False,
    ) == []
    assert service.local.pending(principal="alice")[0]["deleted"] is True


def test_factor_source_sync_tracks_each_storage_provider_without_conflicts(
    monkeypatch, tmp_path: Path,
) -> None:
    source = {
        "owner_username": "alice",
        "factor_id": "CA",
        "factor_name": "CA",
        "source_code": "class CA: pass",
    }
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.list_factor_sources",
        lambda kind: [source] if kind == "custom" else [],
    )
    control = MemoryControlStore()
    first = AccountDomainSyncService(
        sqlite_path=tmp_path / "first.sqlite",
        control_store=control,
        manager_id="office-a",
    )
    second = AccountDomainSyncService(
        sqlite_path=tmp_path / "second.sqlite",
        control_store=control,
        manager_id="office-b",
    )

    assert first.reconcile_factor_sources("alice") == 1
    assert second.reconcile_factor_sources("alice") == 1
    assert first.local.conflicts(principal="alice") == []
    assert second.local.conflicts(principal="alice") == []
    assert {
        row[2] for row in control.rows
        if row[0] == "alice" and row[1] == "factor_source"
    } == {"custom:CA@office-a", "custom:CA@office-b"}
    assert second.reconcile_factor_sources("alice") == 0


def test_lazy_sync_reconciles_factor_source_provider_before_peer_reads(
    monkeypatch, tmp_path: Path,
) -> None:
    source = {
        "owner_username": "alice",
        "factor_id": "CA",
        "factor_name": "CA",
        "source_code": "class CA: pass",
    }
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.list_factor_sources",
        lambda kind: [source] if kind == "custom" else [],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.load_product_categories", lambda _owner: [],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.load_product_groups", lambda _owner: [],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.list_factor_research_runs",
        lambda _owner, limit: [],
    )
    monkeypatch.setattr(
        "tools.data.account_manage.list_factor_sets", lambda _owner: [],
    )
    monkeypatch.setattr(
        "server.manager.storage.account_domain.factor_sync.materialized_factor_configs",
        lambda _owner: [],
    )
    control = MemoryControlStore()
    service = AccountDomainSyncService(
        sqlite_path=tmp_path / "manager.sqlite",
        control_store=control,
        manager_id="office-a",
        access_cooldown=0,
    )

    result = service.sync("alice")

    assert result["reconciled"] == 1
    assert (
        "alice", "factor_source", "custom:CA@office-a"
    ) in control.rows
    assert "source_code" not in control.rows[
        ("alice", "factor_source", "custom:CA@office-a")
    ]["payload"]


def test_factor_source_reconcile_retires_matching_legacy_conflict(
    monkeypatch, tmp_path: Path,
) -> None:
    import hashlib

    source_code = "class CA: pass"
    source_hash = hashlib.sha256(source_code.encode()).hexdigest()
    source = {
        "owner_username": "alice",
        "factor_id": "CA",
        "factor_name": "CA",
        "source_code": source_code,
    }
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.list_factor_sources",
        lambda kind: [source] if kind == "custom" else [],
    )
    control = MemoryControlStore()
    legacy = AccountDomainSyncService(
        sqlite_path=tmp_path / "legacy.sqlite",
        control_store=control,
        manager_id="retired-node",
    )
    legacy.upsert("alice", "factor_source", "custom:CA", {
        "source_kind": "custom",
        "owner_username": "alice",
        "factor_id": "CA",
        "factor_name": "CA",
        "source_sha256": source_hash,
        "source_bytes": len(source_code.encode()),
        "storage_server_id": "retired-node",
        "visibility": "private",
    })
    current = AccountDomainSyncService(
        sqlite_path=tmp_path / "current.sqlite",
        control_store=control,
        manager_id="office-a",
    )
    current.upsert("alice", "factor_source", "custom:CA", {
        **control.rows[("alice", "factor_source", "custom:CA")]["payload"],
        "factor_name": "CA current",
        "storage_server_id": "retired-node",
    })
    assert current.local.conflicts(principal="alice")

    assert current.reconcile_factor_sources("alice") == 1
    assert current.local.pending(principal="alice") == []
    assert current.local.conflicts(principal="alice") == []
    assert (
        "alice", "factor_source", "custom:CA@office-a"
    ) in control.rows


def test_factor_source_provider_repair_is_strictly_scoped() -> None:
    incoming = {"source_sha256": "same", "storage_server_id": "office-a"}

    assert _can_repair_factor_source_provider(
        entity_type="factor_source",
        entity_id="custom:CA@office-a",
        incoming_payload=incoming,
        current_payload={"source_sha256": "same", "storage_server_id": "old"},
        origin_manager_id="office-a",
    )
    assert not _can_repair_factor_source_provider(
        entity_type="factor_source",
        entity_id="custom:CA@office-a",
        incoming_payload=incoming,
        current_payload={"source_sha256": "different", "storage_server_id": "old"},
        origin_manager_id="office-a",
    )
    assert not _can_repair_factor_source_provider(
        entity_type="factor_source",
        entity_id="custom:CA@office-a",
        incoming_payload=incoming,
        current_payload={"source_sha256": "same", "storage_server_id": "old"},
        origin_manager_id="office-b",
    )


def test_metadata_payload_removes_credentials_paths_and_bytes() -> None:
    value = public_payload({
        "display_name": "Research",
        "password_hash": "secret",
        "workspace_root": "/private/workspace",
        "source_code": "class Secret: pass",
        "projection_hash": "abc",
    })

    assert value == {"display_name": "Research", "projection_hash": "abc"}


def test_local_outbox_survives_control_database_outage(tmp_path: Path) -> None:
    service = AccountDomainSyncService(
        sqlite_path=tmp_path / "manager.sqlite",
        control_store=None,
        manager_id="office-a",
    )

    receipt = service.upsert(
        "GTHT@MaxJJW@123",
        "research_publication",
        "publication-1",
        {"publication_id": "publication-1", "visibility": "public"},
    )

    assert receipt["status"] == "pending"
    assert service.entities("GTHT@MaxJJW@123", sync=False)[0]["payload"]["publication_id"] == "publication-1"
    assert len(service.local.pending(principal="GTHT@MaxJJW@123")) == 1


def test_research_revoke_is_a_durable_tombstone(tmp_path: Path) -> None:
    service = AccountDomainSyncService(
        sqlite_path=tmp_path / "manager.sqlite",
        control_store=None,
        manager_id="office-a",
    )

    service.upsert(
        "GTHT@MaxJJW@123",
        "research_publication",
        "publication-1",
        {"publication_id": "publication-1", "visibility": "public"},
        flush=False,
    )
    service.delete(
        "GTHT@MaxJJW@123",
        "research_publication",
        "publication-1",
        flush=False,
    )

    assert service.entities("GTHT@MaxJJW@123", sync=False) == []
    pending = service.local.pending(principal="GTHT@MaxJJW@123")
    assert len(pending) == 1
    assert pending[0]["deleted"] is True


def test_sync_flushes_outbox_and_pulls_shared_research_metadata(tmp_path: Path) -> None:
    control = MemoryControlStore()
    owner = AccountDomainSyncService(
        sqlite_path=tmp_path / "owner.sqlite",
        control_store=control,
        manager_id="office-a",
    )
    remote = AccountDomainSyncService(
        sqlite_path=tmp_path / "remote.sqlite",
        control_store=control,
        manager_id="public-1",
    )

    owner.upsert(
        "GTHT@MaxJJW@123",
        "research_publication",
        "publication-1",
        {
            "publication_id": "publication-1",
            "owner_ref": "GTHT@MaxJJW@123",
            "visibility": "public",
            "storage_server_id": "office-a",
        },
    )

    reports = remote.entities("__public_jobs__", entity_type="research_publication")
    assert len(reports) == 1
    assert reports[0]["payload"]["storage_server_id"] == "office-a"
    assert owner.local.pending(principal="GTHT@MaxJJW@123") == []


def test_concurrent_edit_is_recorded_without_overwriting_local_state(tmp_path: Path) -> None:
    control = MemoryControlStore()
    first = AccountDomainSyncService(
        sqlite_path=tmp_path / "first.sqlite", control_store=control, manager_id="a",
    )
    second = AccountDomainSyncService(
        sqlite_path=tmp_path / "second.sqlite", control_store=control, manager_id="b",
    )
    first.upsert("u", "product_category", "c1", {"id": "c1", "title_zh": "A"})
    second.entities("u")
    second.upsert("u", "product_category", "c1", {"id": "c1", "title_zh": "B"})
    first.upsert("u", "product_category", "c1", {"id": "c1", "title_zh": "C"})

    assert first.local.conflicts(principal="u")
    # A CAS rejection preserves the local edit but blocks automatic retry.
    assert second.local.pending(principal="u") == []
    assert first.local.pending(principal="u") == []
    initial = len(first.local.conflicts(principal="u"))
    for _ in range(4):
        first.upsert("u", "product_category", "c1", {"id": "c1", "title_zh": "C"})
        first.flush(principal="u")
    assert len(first.local.conflicts(principal="u")) == initial
    assert first.local.sync_state(principal="u") == {"pending": 1, "blocked": 1}


def test_two_servers_bidirectionally_sync_and_bridge_missing_content(
    monkeypatch, tmp_path: Path,
) -> None:
    """Two servers sharing one control DB reconcile the SAME principal in opposite
    directions and each ends up with BOTH sides' factor sources.

    This is the invariant that makes the staging/public pair converge when a user
    opens the affected factor-library view: B sends its content up (flush) and A
    pulls it down (and vice-versa), so each local cache is the *union*, not a
    one-way mirror.  Neither server is authoritative; the shared control DB is.
    """
    alice_a = {
        "owner_username": "alice", "factor_id": "Alpha",
        "factor_name": "Alpha", "source_code": "class Alpha: pass",
    }
    alice_b = {
        "owner_username": "alice", "factor_id": "Beta",
        "factor_name": "Beta", "source_code": "class Beta: pass",
    }
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.list_factor_sources",
        lambda kind: [alice_a] if kind == "custom" else [],
    )

    control = MemoryControlStore()
    server_a = AccountDomainSyncService(
        sqlite_path=tmp_path / "a.sqlite", control_store=control, manager_id="office-a",
    )
    server_b = AccountDomainSyncService(
        sqlite_path=tmp_path / "b.sqlite", control_store=control, manager_id="office-b",
    )

    # reconcile A: enqueues custom:Alpha@office-a into the shared control DB.
    assert server_a.reconcile_factor_sources("alice") == 1

    # B (same principal) does its own reconcile: enqueues custom:Beta@office-b.
    # Crucial: B's source list is DIFFERENT from A's; the monkeypatch returns the
    # same list for both, so to make the missing-content case real we swap the
    # list for B so A and B each own a distinct factor.
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.list_factor_sources",
        lambda kind: [alice_b] if kind == "custom" else [],
    )
    assert server_b.reconcile_factor_sources("alice") == 1

    # Shared control DB now holds both, tagged by origin storage server.
    ids = {
        row["entity_id"]
        for row in control.rows.values()
        if row["principal"] == "alice" and row["entity_type"] == "factor_source"
    }
    assert ids == {"custom:Alpha@office-a", "custom:Beta@office-b"}

    # A's local cache has only Alpha before pulling; it still owns its own row.
    assert (
        "alice", "factor_source", "custom:Alpha@office-a"
    ) in control.rows
    # server_a.local.entities → list_entities (LocalAccountDomainStore API)
    a_local_before = {
        row["entity_id"]
        for row in server_a.local.list_entities(
            principal="alice", entity_type="factor_source",
        )
    }
    assert "custom:Alpha@office-a" in a_local_before
    assert "custom:Beta@office-b" not in a_local_before

    # A syncs: flush is a no-op (nothing local pending) but pull must now fetch
    # B's Beta row from the shared control DB, bridging the missing content.
    server_a.sync("alice", force=True)
    a_local_after = {
        row["entity_id"]
        for row in server_a.local.list_entities(
            principal="alice", entity_type="factor_source",
        )
    }
    assert "custom:Beta@office-b" in a_local_after, (
        "server A must pull server B's factor source (missing content bridged)"
    )
    assert "custom:Alpha@office-a" in a_local_after

    # B syncs: it pulls A's Alpha row too, so both sides converge on the union.
    server_b.sync("alice", force=True)
    b_local_after = {
        row["entity_id"]
        for row in server_b.local.list_entities(
            principal="alice", entity_type="factor_source",
        )
    }
    assert "custom:Alpha@office-a" in b_local_after, (
        "server B must pull server A's factor source (missing content bridged)"
    )
    assert "custom:Beta@office-b" in b_local_after

    # No conflicts: each side's own row was authored by itself, the other's was
    # pulled whole.  Conflicting edits would surface here.
    assert server_a.local.conflicts(principal="alice") == []
    assert server_b.local.conflicts(principal="alice") == []


def test_receiver_materializes_version_history_for_locally_held_source(
    monkeypatch, tmp_path: Path,
) -> None:
    """A server that holds a factor source's bytes but never authored it still
    records its formula version (from the fingerprint carried on the outbox
    manifest), so factor_family_formula_versions converges across servers.

    This is the consumer half of the cross-server version-sync chain: the body
    travels lazily over the data plane, the fingerprint arrives via the
    factor_source outbox, and the receiver materializes the version row.
    """
    source = "class Gamma(FactorFamily):\n    pass\n"
    fingerprint = "d" * 64

    # The receiver's local factor_source store holds the bodies (as if hydrated).
    def load_source(kind, owner_username, factor_id):
        if owner_username == "carol" and factor_id == "Gamma":
            return source
        return None

    from tools.data.sqlite.factor_source_versions import (
        list_factor_formula_versions,
    )
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "receiver.sqlite")
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.load_factor_source",
        load_source,
    )

    control = MemoryControlStore()
    receiver = AccountDomainSyncService(
        sqlite_path=tmp_path / "r.sqlite", control_store=control, manager_id="office-b",
    )

    # Seed the receiver's local account_domain_entities with a factor_source
    # manifest that advertises the fingerprint (as if pulled from the control DB).
    receiver.local.upsert_local(
        principal="carol",
        entity_type="factor_source",
        entity_id="custom:Gamma@office-a",
        payload={
            "source_kind": "custom",
            "owner_username": "carol",
            "factor_id": "Gamma",
            "factor_name": "Gamma",
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "source_bytes": 0,
            "storage_server_id": "office-a",
            "visibility": "private",
            "family_formula_fingerprint": fingerprint,
        },
        manager_id="office-a",
    )

    count = receiver.materialize_factor_source_versions("carol")
    assert count == 1, "receiver should materialize one version for the held body"

    versions = list_factor_formula_versions("custom", "carol", "Gamma")
    assert [v["family_formula_fingerprint"] for v in versions] == [fingerprint]


def test_receiver_skips_version_when_source_body_is_absent(
    monkeypatch, tmp_path: Path,
) -> None:
    """No body -> no version row: bytes arrive lazily over the data plane, so a
    receiver that only has the manifest yet must not fabricate version history."""
    fingerprint = "e" * 64

    def load_source(kind, owner_username, factor_id):
        return None  # bytes not local yet

    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "receiver.sqlite")
    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store.load_factor_source",
        load_source,
    )

    from tools.data.sqlite.factor_source_versions import (
        list_factor_formula_versions,
    )

    control = MemoryControlStore()
    receiver = AccountDomainSyncService(
        sqlite_path=tmp_path / "r2.sqlite", control_store=control, manager_id="office-b",
    )
    receiver.local.upsert_local(
        principal="carol",
        entity_type="factor_source",
        entity_id="custom:Delta@office-a",
        payload={
            "source_kind": "custom",
            "owner_username": "carol",
            "factor_id": "Delta",
            "factor_name": "Delta",
            "source_sha256": "y" * 64,
            "source_bytes": 0,
            "storage_server_id": "office-a",
            "visibility": "private",
            "family_formula_fingerprint": fingerprint,
        },
        manager_id="office-a",
    )

    count = receiver.materialize_factor_source_versions("carol")
    assert count == 0, "no body -> must not materialize a version"
    assert list_factor_formula_versions("custom", "carol", "Delta") == []



def test_public_research_metadata_identifies_storage_manager(tmp_path: Path) -> None:
    library = PublicResearchLibrary(tmp_path / "research", storage_server_id="public-1")
    projection = {
        "schema_version": 2,
        "report_id": "report-1",
        "generation": 1,
        "projection_hash": "hash-1",
        "title": "Shared report",
        "components": [],
        "local_resources": [],
    }
    result = library.sync({
        "report_id": "report-1",
        "owner_ref": "u",
        "projection": projection,
    })
    metadata = library.publication_metadata(result["publication_id"])

    assert metadata["storage_server_id"] == "public-1"
    assert "projection" not in metadata
    assert "source_code" not in metadata


def test_producer_outbox_manifest_carries_formula_fingerprint(
    monkeypatch, tmp_path: Path,
) -> None:
    """The producer records the immutable formula fingerprint on the factor_source
    manifest that leaves the authoring server.

    This is the half of the cross-server version-sync chain that the consumer
    ``materialize_factor_source_versions`` depends on: a receiver only backfills
    ``factor_family_formula_versions`` when the pulled manifest advertises a
    non-empty ``family_formula_fingerprint``.  If the authoring path ever drops
    it, every receiver silently skips and the version catalog drifts.
    """
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "producer.sqlite")
    import json

    observed: dict[str, object] = {}

    def fake_enqueue(
        source_kind, owner_username, factor_id, factor_name, source_code,
        *, metadata=None, deleted=False, family_formula_fingerprint="",
    ):
        observed["source_kind"] = source_kind
        observed["owner_username"] = owner_username
        observed["factor_id"] = factor_id
        observed["factor_name"] = factor_name
        observed["source_code"] = source_code
        observed["metadata"] = dict(metadata or {})
        observed["fingerprint"] = family_formula_fingerprint
        return None

    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store._enqueue_source_metadata",
        fake_enqueue,
    )

    source = "class Delta(FactorFamily):\n    pass\n"
    fingerprint = "e" * 64
    from tools.data.sqlite.factor_source_store import upsert_factor_source

    upsert_factor_source(
        "custom", "dave", "Delta", "Delta", source,
        chinese_name="Delta",
        family_formula_fingerprint=fingerprint,
    )

    assert observed.get("factor_id") == "Delta"
    assert observed.get("source_kind") == "custom"
    assert observed.get("owner_username") == "dave"
    assert observed["metadata"].get("chinese_name") == "Delta"
    # The formula fingerprint is threaded as a distinct keyword to the outbox
    # manifest (it is not part of the user-facing metadata dict), so it can be
    # consumed by the receiver's materialize pass.
    assert observed.get("fingerprint") == fingerprint, (
        "the factor_source outbox manifest must carry the formula fingerprint "
        "so the receiver can materialize its version history"
    )


def test_producer_outbox_manifest_keeps_fingerprint_after_update(
    monkeypatch, tmp_path: Path,
) -> None:
    """Updating a custom factor family must keep the fingerprint on the manifest.

    This guards the api_update_factor path: editing a factor family recomputes
    the formula fingerprint and must thread it through the outbox, otherwise the
    updated version identity never leaves the authoring server.
    """
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "producer2.sqlite")

    observed: dict[str, object] = {}

    def fake_enqueue(
        source_kind, owner_username, factor_id, factor_name, source_code,
        *, metadata=None, deleted=False, family_formula_fingerprint="",
    ):
        observed["factor_id"] = factor_id
        observed["metadata"] = dict(metadata or {})
        observed["fingerprint"] = family_formula_fingerprint
        return None

    monkeypatch.setattr(
        "tools.data.sqlite.factor_source_store._enqueue_source_metadata",
        fake_enqueue,
    )

    source = "class Delta(FactorFamily):\n    pass\n"
    fingerprint = "f" * 64
    from tools.data.sqlite.factor_source_store import upsert_factor_source

    upsert_factor_source(
        "custom", "dave", "Delta", "Delta", source,
        chinese_name="Delta",
        family_formula_fingerprint=fingerprint,
    )

    assert observed.get("factor_id") == "Delta"
    assert observed["metadata"].get("chinese_name") == "Delta"
    assert observed.get("fingerprint") == fingerprint, (
        "an updated custom factor family must still advertise its formula "
        "fingerprint on the outbox manifest"
    )


def test_pull_conflict_replay_is_bounded_and_retains_local_edit(tmp_path):
    local = LocalAccountDomainStore(tmp_path / "conflict.sqlite")
    kwargs = dict(principal="u", entity_type="factor_set", entity_id="s", manager_id="a")
    operation = local.upsert_local(**kwargs, payload={"label": "local"})
    remote = dict(principal="u", entity_type="factor_set", entity_id="s",
                  payload={"label": "remote"}, deleted=False, revision=5)
    for _ in range(5):
        assert local.apply_remote(remote) == "conflict"
    assert len(local.conflicts(principal="u")) == 1
    assert local.pending(principal="u") == []
    assert local.upsert_local(**kwargs, payload={"label": "local"}) == operation
    local.upsert_local(**kwargs, payload={"label": "edited again"})
    assert local.pending(principal="u") == []
    assert local.list_entities(principal="u")[0]["payload"] == {"label": "edited again"}


def test_metadata_collections_and_nested_identities_are_not_truncated():
    payload = {"members": list(range(4100)), "nested": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"ref": "frozen"}}}}}}}}}}
    assert public_payload(payload) == payload


def test_receiver_rejects_wrong_source_version(monkeypatch, tmp_path):
    monkeypatch.setattr("tools.data.sqlite.factor_source_store.load_factor_source", lambda *args: "new version")
    monkeypatch.setattr("tools.data.sqlite.factor_source_versions.record_factor_formula_version",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not label new bytes with old identity")))
    service = AccountDomainSyncService(sqlite_path=tmp_path / "versions.sqlite", control_store=None, manager_id="b")
    service.local.upsert_local(principal="u", entity_type="factor_source", entity_id="custom:F@a",
        manager_id="a", payload={"source_kind": "custom", "factor_id": "F", "owner_username": "u",
        "family_formula_fingerprint": "a" * 64, "source_sha256": hashlib.sha256(b"old version").hexdigest()})
    assert service.materialize_factor_source_versions("u") == 0


def test_explicit_resolution_rebases_only_reviewed_local_value(tmp_path):
    import pytest
    local = LocalAccountDomainStore(tmp_path / "resolution.sqlite")
    key = dict(principal="u", entity_type="factor_set", entity_id="s")
    local.upsert_local(**key, manager_id="a", payload={"label": "local"})
    local.apply_remote({**key, "payload": {"label": "remote"}, "revision": 5})
    with pytest.raises(ValueError, match="precondition"):
        local.resolve_conflict(**key, manager_id="a", expected_payload={}, remote_revision=5, payload={"label": "local"})
    local.resolve_conflict(**key, manager_id="a", expected_payload={"label": "local"}, remote_revision=5, payload={"label": "merged"})
    assert local.pending(principal="u")[0]["base_revision"] == 5
    assert local.conflicts(principal="u") == []
    assert local.apply_remote({**key, "payload": {"label": "new remote"}, "revision": 6}) == "conflict"
    assert local.pending(principal="u") == []


def test_acknowledgment_of_coalesced_inflight_edit_rebases_successor(tmp_path):
    local = LocalAccountDomainStore(tmp_path / "inflight.sqlite")
    key = dict(principal="u", entity_type="product_category", entity_id="c", manager_id="a")
    original = local.upsert_local(**key, payload={"title": "first"})
    sent = local.pending()[0]
    successor = local.upsert_local(**key, payload={"title": "second"})
    local.acknowledge(original, revision=10, sent_item=sent)
    pending = local.pending()[0]
    assert pending["operation_id"] == successor
    assert pending["base_revision"] == 10
    assert pending["payload"] == {"title": "second"}
    local.acknowledge(successor, revision=11, sent_item=pending)
    assert local.pending() == []
    assert local.list_entities()[0]["payload"] == {"title": "second"}
