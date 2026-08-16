from __future__ import annotations

from server.manager.services.account_domain_projection import factor_rows_from_sync
from server.manager.services.client_state import ClientStateService


class LocalOnlySync:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.sync_flags = []

    def entities(self, _principal, *, entity_type="", include_shared=True, sync=True):
        self.sync_flags.append(sync)
        assert sync is False
        return [
            row for row in self.rows
            if not entity_type or row.get("entity_type") == entity_type
        ]


class LocalAccounts:
    def load_accounts(self):
        return [{
            "username": "GTHT@MaxJJW@392452984564",
            "alias": "MaxJJW",
            "organization_id": "GTHT",
            "organization_name": "GTHT",
        }]


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
    assert sync.sync_flags == [False]


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
