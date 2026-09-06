from threading import Event

from server.manager.services.client_state import ClientStateService


def test_refresh_waits_for_read_after_write_and_bypasses_cooldown(tmp_path, monkeypatch):
    calls = []

    class Sync:
        access_cooldown = 100

        def sync(self, principal, *, force=False):
            calls.append((principal, force))
            return {"status": "synced"}

    monkeypatch.setattr(
        "server.manager.services.subordinate_factor_library.direct_subordinate_accounts",
        lambda *args: [],
    )
    client = ClientStateService(tmp_path, account_domain_sync=Sync())
    assert client.refresh_account_catalog("alice")["status"] == "synced"
    assert client.refresh_account_catalog("alice")["status"] == "synced"
    assert calls == [("alice", True), ("alice", True)]


def test_write_during_inflight_refresh_requests_another_pass(tmp_path, monkeypatch):
    entered, finish, repeated = Event(), Event(), Event()
    calls = []

    class Sync:
        access_cooldown = 100

        def sync(self, principal, *, force=False):
            calls.append(force)
            if len(calls) == 1:
                entered.set()
                assert finish.wait(2)
            else:
                repeated.set()
            return {"status": "synced"}

    monkeypatch.setattr(
        "server.manager.services.subordinate_factor_library.direct_subordinate_accounts",
        lambda *args: [],
    )
    client = ClientStateService(tmp_path, account_domain_sync=Sync())
    client._refresh_account_domain_async("alice")
    assert entered.wait(2)
    client._refresh_account_domain_async("alice", force=True)
    finish.set()
    assert repeated.wait(2)
    assert calls == [False, True]
