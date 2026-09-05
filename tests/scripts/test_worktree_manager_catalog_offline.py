from __future__ import annotations

import threading

from server.manager.services.account_domain_projection import factor_rows_from_sync
from server.manager.services.client_state import ClientStateService
from tools.factors.formula_identity import freeze_factor_identity


def _factor(alias: str, family: str, owner: str) -> dict:
    return freeze_factor_identity(
        owner_ref=owner,
        family_alias=family,
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"$F": "1m"} if "$F:1m" in alias else {},
    )


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
            "resolved_factors": [_factor(
                "SgCCS|$F:1m", "SgCCS", "GTHT@MaxJJW@392452984564",
            )],
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
            "resolved_factors": [_factor(
                "CA|$F:1m", "CA", "GTHT@MaxJJW@392452984564",
            )],
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
            "resolved_factors": [_factor(
                "ParentFactor", "ParentFactor", parent,
            )],
        },
    }, {
        "principal": child,
        "entity_type": "factor_param_config",
        "entity_id": "default:CA",
        "payload": {
            "factor_family_alias": "CA",
            "resolved_factors": [_factor("CA|$F:1m", "CA", child)],
        },
    }, {
        "principal": peer,
        "entity_type": "factor_param_config",
        "entity_id": "default:PeerFactor",
        "payload": {
            "factor_family_alias": "PeerFactor",
            "resolved_factors": [_factor("PeerFactor", "PeerFactor", peer)],
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
    from tools.factors.factor_set_identity import freeze_factor_set_identity
    sets = {name: {**freeze_factor_set_identity(owner_ref=f"principal:{owner}", set_id=name,
               alias=name, members=[_factor("F", "F", owner)]), "owner_username": owner}
            for name, owner in [("mine", parent), ("child", child), ("peer", peer)]}
    sync = LocalOnlySync([
        {"principal": owner, "entity_type": "factor_set", "entity_id": sets[name]["ref"], "payload": sets[name]}
        for name, owner in [("mine", parent), ("child", child), ("peer", peer)]
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

    assert [item["target_ref"] for item in scopes["mine"]] == [sets["mine"]["ref"]]
    assert [item["target_ref"] for item in scopes["subordinates"]] == [sets["child"]["ref"]]


def test_mirrored_v2_set_detail_and_runspec_descriptor_preserve_members(tmp_path, monkeypatch):
    from tools.factors.factor_set_identity import freeze_factor_set_identity
    members = [_factor("F1", "F", "alice"), _factor("G1", "G", "alice")]
    frozen = {**freeze_factor_set_identity(owner_ref="principal:alice", set_id="s", alias="Set", members=members),
              "owner_username": "alice"}
    sync = LocalOnlySync([{"principal": "alice", "entity_type": "factor_set", "entity_id": frozen["ref"], "payload": frozen}])
    monkeypatch.setattr("server.modules.custom_factors.factor_set_registry.get_factor_set", lambda *args: None)
    service = ClientStateService(tmp_path / "client", account_domain_sync=sync, local_account_store=LocalAccounts())
    detail = service.factor_set_detail("alice", frozen["ref"], offset=0, limit=1)
    assert detail["member_count"] == 2 and detail["has_more"]
    assert detail["related_references"][0]["data"] in members
    descriptor = service.factor_set_descriptor("alice", frozen["ref"])
    assert descriptor["target_ref"] == frozen["ref"]
    assert descriptor["manifest"]["identity"] == frozen["identity"]
