from __future__ import annotations

from pathlib import Path

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
    # The second edit has a fresh remote base and wins; the stale first edit
    # remains pending and is reported as a conflict when it is retried.
    assert second.local.pending(principal="u") == []
    assert first.local.pending(principal="u")


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
