from __future__ import annotations

import threading

from server.manager.services.client_state import ClientStateService
from server.manager.storage.account_domain.service import AccountDomainSyncService


class _Sync:
    access_cooldown = 5.0

    def __init__(self) -> None:
        self.rows: list[dict] = [{
            "principal": "alice",
            "entity_type": "product_group",
            "entity_id": "group-1",
            "payload": {"id": "group-1", "name": "我的产品组"},
            "deleted": False,
        }]
        self.sync_calls: list[str] = []
        self.started = threading.Event()

    def sync(self, principal: str):
        self.sync_calls.append(principal)
        self.started.set()
        return {"status": "synced"}

    def entities(
        self,
        principal: str,
        *,
        entity_type: str = "",
        include_shared: bool = True,
        include_deleted: bool = False,
        sync: bool = True,
    ) -> list[dict]:
        assert principal == "alice"
        assert entity_type == "product_group"
        assert include_shared is False
        assert include_deleted is False
        assert sync is False
        return list(self.rows)


def test_account_catalog_reads_local_mirror_and_shares_one_async_refresh() -> None:
    synchronizer = _Sync()
    state = ClientStateService(account_domain_sync=synchronizer)

    first = state._account_catalog_entities(
        "alice", entity_type="product_group", include_shared=False,
    )
    second = state._account_catalog_entities(
        "alice", entity_type="product_group", include_shared=False,
    )

    assert first == second == synchronizer.rows
    assert synchronizer.started.wait(timeout=1)
    assert synchronizer.sync_calls == ["alice"]


def test_account_catalog_can_project_tombstones_for_authoritative_merge(
    tmp_path,
) -> None:
    synchronizer = AccountDomainSyncService(
        sqlite_path=tmp_path / "account.sqlite",
        control_store=None,
        manager_id="manager-1",
    )
    synchronizer.local.upsert_local(
        principal="alice",
        entity_type="product_group",
        entity_id="deleted-group",
        payload={"id": "deleted-group", "name": "已删除"},
        manager_id="manager-1",
        deleted=True,
    )

    rows = synchronizer.entities(
        "alice",
        entity_type="product_group",
        include_shared=False,
        include_deleted=True,
        sync=False,
    )

    assert len(rows) == 1
    assert rows[0]["entity_id"] == "deleted-group"
    assert rows[0]["deleted"] is True
