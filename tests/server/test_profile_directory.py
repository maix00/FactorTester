from __future__ import annotations

import server.manager.services.profile_directory as directory_module
from server.manager.services.profile_directory import ProfileDirectoryService
from server.manager.storage.agent_conversation_store import AgentConversationStore

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
    def __init__(self, store=None, items=None):
        self.store = store
        self._items = items or {}

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

    def conversation_items(
        self, principal, profile_id, conversation_id, **_options,
    ):
        return {
            "items": [dict(item) for item in self._items.get(
                (principal, profile_id, conversation_id), [],
            )],
            "has_more": False,
            "after": None,
            "turn_count": 1,
        }


class FakeFederatedProfiles:
    def __init__(self, profiles, conversations=None, items=None):
        self._profiles = profiles
        self._conversations = conversations or {}
        self._items = items or {}

    def profile_directory(self, owners):
        return [
            dict(item) for item in self._profiles
            if item.get("owner_ref") in owners
        ]

    def profile_conversations(self, source, _viewer, owner, profile_id):
        return [
            dict(item)
            for item in self._conversations.get((source, owner, profile_id), [])
        ]

    def profile_conversation_items(
        self, source, _viewer, owner, profile_id, conversation_id, **_options,
    ):
        return {
            "items": [
                dict(item)
                for item in self._items.get(
                    (source, owner, profile_id, conversation_id),
                    [],
                )
            ],
            "has_more": False,
            "after": None,
            "turn_count": 1,
        }


def _profile(owner, profile_id, *, visibility="private"):
    return {
        "profile_id": profile_id,
        "display_name": profile_id.upper(),
        "visibility": visibility,
        "session_binding": {"principal_ref": owner},
    }


def _service(monkeypatch, client, agent, *, server_id="local-1", federated=None):
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
        federated_public_data=federated,
        conversation_items_reader=agent.conversation_items,
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


def test_reserved_self_profile_uses_viewer_relative_display_name(monkeypatch):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    client = FakeClientState({
        parent: [{**_profile(parent, "self"), "profile_kind": "self"}],
        child: [{**_profile(child, "self"), "profile_kind": "self"}],
    })
    service = _service(monkeypatch, client, FakeAgentProfiles())

    mine = service.directory(parent, scope="mine")["items"][0]
    subordinate = service.directory(parent, scope="subordinates")["items"][0]

    assert mine["display_name"] == "本人"
    assert mine["profile_kind"] == "self"
    assert mine["is_self_profile"] is True
    assert mine["capabilities"]["edit"] is True
    assert subordinate["display_name"] == "child"
    assert subordinate["profile_kind"] == "self"
    assert subordinate["is_self_profile"] is True
    assert subordinate["capabilities"]["edit"] is False


def test_mine_directory_lazily_ensures_reserved_self_profile(monkeypatch):
    owner = "GTHT@parent@100000000001"

    class EnsuringClientState(FakeClientState):
        def __init__(self):
            super().__init__({owner: []})
            self.ensured = []

        def ensure_self_profile(self, principal):
            self.ensured.append(principal)
            self._profiles[principal] = [{
                **_profile(principal, "self"),
                "profile_kind": "self",
            }]

    client = EnsuringClientState()
    service = _service(monkeypatch, client, FakeAgentProfiles())

    result = service.directory(owner, scope="mine")

    assert client.ensured == [owner]
    assert result["total"] == 1
    assert result["items"][0]["profile_id"] == "self"


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


def test_subordinate_directory_merges_mirrored_profile_projections(monkeypatch):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    client = FakeClientState({
        child: [_profile(child, "child-profile")],
    })
    remote = {
        **_profile(child, "child-profile"),
        "owner_ref": child,
        "source_server_id": "remote-main",
        "runtime": {
            "runtime_kind": "server",
            "executor_id": "remote-main",
            "configured": True,
        },
        "active_claim": {"agent_id": "agent-remote", "status": "stopped"},
        "conversation_count": 3,
    }
    service = _service(
        monkeypatch,
        client,
        FakeAgentProfiles(),
        federated=FakeFederatedProfiles([
            {**_profile(child, "child-profile"), "owner_ref": child, "source_server_id": "local-1"},
            remote,
        ]),
    )

    result = service.directory(parent, scope="subordinates")

    assert result["total"] == 1
    item = result["items"][0]
    assert item["owner_ref"] == child
    assert item["source_server_ids"] == ["local-1", "remote-main"]
    assert item["source_server_id"] == "remote-main"
    assert item["profile_key"] == f"remote-main::{child}::child-profile"
    assert item["agent_id"] == "agent-remote"
    assert item["conversation_count"] == 3


def test_conversation_visibility_is_automatic_for_direct_parent(monkeypatch, tmp_path):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    store = AgentConversationStore(tmp_path / "manager.sqlite")
    conversation = store.create(child, "child-profile")
    store.update_runtime_observation(
        child,
        "child-profile",
        conversation["conversation_id"],
        actual_model="research-model",
        model_context_window=200000,
        total_tokens=45000,
        last_tokens=12000,
        compaction_count=1,
    )
    client = FakeClientState({child: [_profile(child, "child-profile")]})
    agent = FakeAgentProfiles(store, items={(
        child, "child-profile", conversation["conversation_id"],
    ): [{
        "id": "assistant-1",
        "type": "assistant_message",
        "content": [{
            "type": "output_text",
            "text": "token=secret /Users/private/workspace/report.png",
            "annotations": [],
        }],
        "created_at": "2026-08-20T00:00:00+00:00",
    }]})
    service = _service(monkeypatch, client, agent)

    assert service.can_view_conversations(parent, child, {"conversation_sharing": False})
    store.set_parent_sharing(child, "child-profile", True)
    assert service.can_view_conversations(parent, child, {"conversation_sharing": True})
    conversations = service.conversations(
        parent,
        "local-1::GTHT@child@100000000002::child-profile",
        scope="subordinates",
    )
    assert conversations[0]["actual_model"] == "research-model"
    assert conversations[0]["model_context_window"] == 200000
    assert conversations[0]["last_tokens"] == 12000
    items = service.conversation_items(
        parent,
        "local-1::GTHT@child@100000000002::child-profile",
        conversation["conversation_id"],
        scope="subordinates",
    )
    assert items["items"][0]["type"] == "assistant_message"
    assert "token=secret" in items["items"][0]["content"][0]["text"]
    assert "/Users/private/workspace/report.png" in items["items"][0]["content"][0]["text"]


def test_mirrored_profile_reads_from_executing_server_even_for_stale_local_key(
    monkeypatch,
    tmp_path,
):
    parent = "GTHT@parent@100000000001"
    child = "GTHT@child@100000000002"
    profile_id = "child-profile"
    conversation_id = "conversation-remote"
    client = FakeClientState({child: [_profile(child, profile_id)]})
    remote_profile = {
        **_profile(child, profile_id),
        "owner_ref": child,
        "source_server_id": "remote-main",
        "runtime": {
            "runtime_kind": "server",
            "executor_id": "remote-main",
            "configured": True,
        },
        "active_claim": {"agent_id": "agent-remote", "status": "running"},
    }
    federated = FakeFederatedProfiles(
        [{**_profile(child, profile_id), "owner_ref": child, "source_server_id": "local-1"}, remote_profile],
        conversations={(
            "remote-main", child, profile_id,
        ): [{
            "conversation_id": conversation_id,
            "profile_id": profile_id,
            "title": "远端最新会话",
            "updated_at": 10,
        }]},
        items={(
            "remote-main", child, profile_id, conversation_id,
        ): [{"id": "item-1", "role": "assistant", "text": "来自远端", "created_at": 10}]},
    )
    service = _service(
        monkeypatch,
        client,
        FakeAgentProfiles(AgentConversationStore(tmp_path / "manager.sqlite")),
        federated=federated,
    )

    stale_key = f"local-1::{child}::{profile_id}"
    conversations = service.conversations(parent, stale_key, scope="subordinates")
    items = service.conversation_items(
        parent, stale_key, conversation_id, scope="subordinates",
    )

    assert conversations[0]["title"] == "远端最新会话"
    assert items["items"][0]["text"] == "来自远端"
