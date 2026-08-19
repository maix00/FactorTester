from __future__ import annotations

from server.manager.services.profile_directory import ProfileDirectoryService
from server.manager.storage.agent_conversation_store import AgentConversationStore
import server.manager.services.profile_directory as directory_module


ACCOUNTS = {
    "GTHT@parent@100000000001": {
        "username": "GTHT@parent@100000000001",
        "alias": "parent",
        "parent_username": "",
        "active": True,
    },
    "GTHT@child@100000000002": {
        "username": "GTHT@child@100000000002",
        "alias": "child",
        "parent_username": "GTHT@parent@100000000001",
        "active": True,
    },
    "GTHT@grandchild@100000000003": {
        "username": "GTHT@grandchild@100000000003",
        "alias": "grandchild",
        "parent_username": "GTHT@child@100000000002",
        "active": True,
    },
}


class FakeClientState:
    def __init__(self, profiles):
        self._profiles = profiles

    def profiles(self, principal, *, include_local_paths=False):
        return [dict(item) for item in self._profiles.get(principal, [])]


class FakeAgentProfiles:
    def __init__(self, store=None):
        self.store = store

    def enrich(self, principal, profiles):
        result = []
        for profile in profiles:
            value = dict(profile)
            value.setdefault("runtime", {
                "runtime_kind": "server",
                "executor_id": "local-1",
                "configured": True,
            })
            value.setdefault("active_claim", None)
            result.append(value)
        return result

    def conversations(self, principal, profile_id):
        return self.store.list(principal, profile_id) if self.store else []

    def conversation_sharing(self, principal, profile_id):
        return self.store.parent_sharing(principal, profile_id) if self.store else False

    def conversation_items(self, principal, profile_id, conversation_id):
        return self.store.items(principal, profile_id, conversation_id) if self.store else []


def _profile(owner, profile_id, *, visibility="private"):
    return {
        "profile_id": profile_id,
        "display_name": profile_id.upper(),
        "visibility": visibility,
        "session_binding": {"principal_ref": owner},
    }


def _service(monkeypatch, client, agent, *, server_id="local-1"):
    monkeypatch.setattr(directory_module, "load_accounts", lambda: list(ACCOUNTS.values()))
    monkeypatch.setattr(
        directory_module,
        "get_account",
        lambda username: ACCOUNTS.get(username),
    )
    monkeypatch.setattr(
        directory_module,
        "is_super_admin_account",
        lambda account: bool(account and account.get("super_admin")),
    )
    monkeypatch.setattr(
        directory_module,
        "direct_subordinate_accounts_for",
        lambda username: [
            item for item in ACCOUNTS.values()
            if item.get("parent_username") == username and item.get("active")
        ],
    )
    return ProfileDirectoryService(
        server_id=server_id,
        client_state=client,
        agent_profiles=agent,
    )


def test_directory_uses_composite_identity_and_direct_subordinates(monkeypatch):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    grandchild = "GTHT@grandchild@100000000003"
    client = FakeClientState({
        parent: [_profile(parent, "same")],
        child: [_profile(child, "child-profile")],
        grandchild: [_profile(grandchild, "grandchild-profile")],
    })
    service = _service(monkeypatch, client, FakeAgentProfiles())

    subordinate = service.directory(parent, scope="subordinates")
    assert [item["owner_ref"] for item in subordinate["items"]] == [child]
    assert subordinate["items"][0]["read_only"] is True

    mine = service.directory(parent, scope="mine")
    assert mine["items"][0]["profile_key"] == "local-1::GTHT@parent@100000000001::same"


def test_servers_scope_hides_private_profiles_for_regular_users(monkeypatch):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    client = FakeClientState({
        parent: [_profile(parent, "mine")],
        child: [
            _profile(child, "private-child"),
            _profile(child, "public-child", visibility="public"),
        ],
    })
    service = _service(monkeypatch, client, FakeAgentProfiles())

    result = service.directory(parent, scope="servers")
    ids = {item["profile_id"] for item in result["items"]}
    assert ids == {"mine", "public-child"}
    assert next(item for item in result["items"] if item["profile_id"] == "mine")["read_only"] is False
    assert next(item for item in result["items"] if item["profile_id"] == "public-child")["read_only"] is True


def test_conversation_visibility_requires_direct_parent_sharing(monkeypatch, tmp_path):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    store = AgentConversationStore(tmp_path / "manager.sqlite")
    conversation = store.create(child, "child-profile")
    store.append_item(
        child,
        "child-profile",
        conversation["conversation_id"],
        role="assistant",
        text="token=secret /Users/private/workspace/report.png",
    )
    client = FakeClientState({child: [_profile(child, "child-profile")]})
    agent = FakeAgentProfiles(store)
    service = _service(monkeypatch, client, agent)

    assert not service.can_view_conversations(parent, child, {"conversation_sharing": False})
    store.set_parent_sharing(child, "child-profile", True)
    assert service.can_view_conversations(parent, child, {"conversation_sharing": True})
    items = service.conversation_items(
        parent,
        "local-1::GTHT@child@100000000002::child-profile",
        conversation["conversation_id"],
        scope="subordinates",
    )
    assert items[0]["role"] == "assistant"
    assert "[redacted]" in items[0]["text"]
    assert "[server path redacted]" in items[0]["text"]
