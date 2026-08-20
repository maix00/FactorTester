from __future__ import annotations

import threading

from server.manager.services.account_domain_projection import factor_rows_from_sync
from server.manager.services.client_state import ClientStateService


class LocalOnlySync:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.sync_flags = []

    def entities(self, principal, *, entity_type="", include_shared=True, sync=True):
        self.sync_flags.append(sync)
        assert sync is False
        return [
            row for row in self.rows
            if row.get("principal") == principal
            and (not entity_type or row.get("entity_type") == entity_type)
        ]


class LocalAccounts:
    def __init__(self, rows=None):
        self.rows = rows

    def load_accounts(self):
        return self.rows or [{
            "username": "GTHT@MaxJJW@392452984564",
            "alias": "MaxJJW",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
        }]


def test_catalog_read_returns_local_mirror_before_background_refresh(tmp_path):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class SlowSync(LocalOnlySync):
        def sync(self, principal):
            assert principal == "alice"
            started.set()
            release.wait(timeout=2)
            self.rows.append({
                "principal": "alice",
                "entity_type": "product_category",
                "entity_id": "remote-category",
                "payload": {"id": "remote-category", "title_zh": "远端分类"},
            })
            finished.set()

    sync = SlowSync()
    service = ClientStateService(
        tmp_path / "client",
        account_domain_sync=sync,
        local_account_store=LocalAccounts(),
    )

    initial = service.product_categories("alice")

    assert not any(item.get("id") == "remote-category" for item in initial)
    assert started.wait(timeout=1)
    release.set()
    assert finished.wait(timeout=1)
    refreshed = service.product_categories("alice")
    assert any(item.get("id") == "remote-category" for item in refreshed)


def test_factor_projection_uses_local_owner_alias_and_hides_migrated_username():
    sync = LocalOnlySync([{
        "principal": "GTHT@MaxJJW@392452984564",
        "entity_type": "factor_param_config",
        "entity_id": "default:SgCCS",
        "payload": {
            "id": "GTHT@MaxJJW@392452984564",
            "name": "GTHT@MaxJJW@392452984564",
            "scope_user_id": "GTHT@MaxJJW@392452984564",
            "params_list": [{"$F": "1m"}],
            "resolved_factors": [{
                "factor_alias": "SgCCS|$F:1m",
                "factor_family_alias": "SgCCS",
                "params": [{"alias": "$F", "value": "1m"}],
            }],
        },
    }])

    rows = factor_rows_from_sync(
        sync,
        "GTHT@MaxJJW@392452984564",
        owner_account=LocalAccounts().load_accounts()[0],
    )

    assert rows[0]["owner_username"] == "GTHT@MaxJJW@392452984564"
    assert rows[0]["owner_alias"] == "MaxJJW"
    assert rows[0]["factor_family_alias"] == "SgCCS"
    assert rows[0]["factor_family_name"] == "SgCCS"
    assert rows[0]["factor_alias"] == "SgCCS|$F:1m"
    assert sync.sync_flags == [False]


def test_factor_projection_never_manufactures_index_aliases():
    sync = LocalOnlySync([{
        "principal": "alice",
        "entity_type": "factor_param_config",
        "entity_id": "default:CA",
        "payload": {
            "factor_family_alias": "CA",
            "params_list": [{"$F": "1m"}, {"$F": "1d"}],
        },
    }])

    assert factor_rows_from_sync(sync, "alice") == []


def test_factor_library_prefers_resolved_sqlite_mirror_without_legacy_rebuild(
    tmp_path, monkeypatch,
):
    class ResolvedSync(LocalOnlySync):
        def reconcile_factor_catalog(self, principal):
            assert principal == "GTHT@MaxJJW@392452984564"

        def sync(self, principal):
            assert principal == "GTHT@MaxJJW@392452984564"
            return {"status": "synced"}

    sync = ResolvedSync([{
        "principal": "GTHT@MaxJJW@392452984564",
        "entity_type": "factor_param_config",
        "entity_id": "default:CA",
        "payload": {
            "factor_family_alias": "CA",
            "resolved_factors": [{
                "factor_alias": "CA|$F:1m",
                "factor_family_alias": "CA",
                "params": [{"alias": "$F", "value": "1m"}],
            }],
        },
    }])
    monkeypatch.setattr(
        "server.modules.custom_factors.factor_library_service.build_factor_library_overview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy factor rebuild must not run")
        ),
    )
    service = ClientStateService(
        tmp_path / "client",
        account_domain_sync=sync,
        local_account_store=LocalAccounts(),
    )

    value = service.factor_library("GTHT@MaxJJW@392452984564")

    assert [item["factor_alias"] for item in value["factors"]] == ["CA|$F:1m"]


def test_factor_library_subordinates_are_direct_children_from_sync_mirror(
    tmp_path, monkeypatch,
):
    parent = "GTHT@testA@545963541963"
    child = "GTHT@MaxJJW@392452984564"
    peer = "GTHT@peer@123456789012"
    accounts = LocalAccounts([
        {"username": parent, "alias": "testA", "organization_id": "GTHT"},
        {"username": child, "alias": "MaxJJW", "organization_id": "GTHT",
         "parent_username": parent, "active": True},
        {"username": peer, "alias": "peer", "organization_id": "GTHT",
         "parent_username": "", "active": True},
    ])
    sync = LocalOnlySync([{
        "principal": parent,
        "entity_type": "factor_param_config",
        "entity_id": "default:ParentFactor",
        "payload": {
            "factor_family_alias": "ParentFactor",
            "resolved_factors": [{
                "factor_alias": "ParentFactor",
                "factor_family_alias": "ParentFactor",
            }],
        },
    }, {
        "principal": child,
        "entity_type": "factor_param_config",
        "entity_id": "default:CA",
        "payload": {
            "factor_family_alias": "CA",
            "resolved_factors": [{
                "factor_alias": "CA|$F:1m",
                "factor_family_alias": "CA",
            }],
        },
    }, {
        "principal": peer,
        "entity_type": "factor_param_config",
        "entity_id": "default:PeerFactor",
        "payload": {
            "factor_family_alias": "PeerFactor",
            "resolved_factors": [{
                "factor_alias": "PeerFactor",
                "factor_family_alias": "PeerFactor",
            }],
        },
    }])
    monkeypatch.setattr(
        "server.modules.custom_factors.factor_library_service.build_factor_library_overview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("subordinate rows must use the sync mirror")
        ),
    )
    service = ClientStateService(
        tmp_path / "client",
        account_domain_sync=sync,
        local_account_store=accounts,
    )

    value = service.factor_library_scopes(parent)["subordinates"]

    assert [item["factor_alias"] for item in value["factors"]] == ["CA|$F:1m"]
    assert value["factors"][0]["owner_username"] == child


def test_profile_read_does_not_wait_for_control_database(tmp_path):
    class FailingControlStore:
        def list_profiles(self, _principal):
            raise ConnectionError("postgresql is offline")

    sync = LocalOnlySync()
    service = ClientStateService(
        tmp_path / "client",
        control_store=FailingControlStore(),
        profile_cache_root=tmp_path / "profile-cache",
        account_domain_sync=sync,
        local_account_store=LocalAccounts(),
    )

    assert service.profiles("GTHT@MaxJJW@392452984564") == []
    assert sync.sync_flags == [False]


def test_factor_set_scopes_include_only_direct_children(tmp_path, monkeypatch):
    parent = "GTHT@testA@545963541963"
    child = "GTHT@MaxJJW@392452984564"
    peer = "GTHT@peer@123456789012"
    accounts = LocalAccounts([
        {"username": parent, "alias": "testA", "organization_id": "GTHT"},
        {"username": child, "alias": "MaxJJW", "organization_id": "GTHT",
         "parent_username": parent, "active": True},
        {"username": peer, "alias": "peer", "organization_id": "GTHT",
         "parent_username": "", "active": True},
    ])
    sync = LocalOnlySync([
        {"principal": parent, "entity_type": "factor_set", "entity_id": "mine",
         "payload": {"target_ref": "set:mine", "set_id": "mine"}},
        {"principal": child, "entity_type": "factor_set", "entity_id": "child",
         "payload": {"target_ref": "set:child", "set_id": "child"}},
        {"principal": peer, "entity_type": "factor_set", "entity_id": "peer",
         "payload": {"target_ref": "set:peer", "set_id": "peer"}},
    ])
    monkeypatch.setattr(
        "server.modules.custom_factors.factor_set_registry.factor_set_catalog",
        lambda *_args, **_kwargs: [],
    )
    service = ClientStateService(
        tmp_path / "client", account_domain_sync=sync,
        local_account_store=accounts,
    )

    scopes = service.factor_set_scopes(parent)

    assert [item["target_ref"] for item in scopes["mine"]] == ["set:mine"]
    assert [item["target_ref"] for item in scopes["subordinates"]] == ["set:child"]
