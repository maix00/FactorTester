from __future__ import annotations

import sqlite3

from server.manager.storage.agent_conversation_store import (
    AgentConversationStore,
    ITEM_TABLE,
)


def test_conversation_catalog_removes_legacy_message_mirror(tmp_path):
    db_path = tmp_path / "manager.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute(f"CREATE TABLE {ITEM_TABLE}(text TEXT)")
        db.execute(f"INSERT INTO {ITEM_TABLE}(text) VALUES ('legacy')")

    AgentConversationStore(db_path)

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ITEM_TABLE,),
        ).fetchone()
    assert row is None


def test_conversation_catalog_is_scoped_by_principal_and_profile(tmp_path):
    store = AgentConversationStore(tmp_path / "manager.sqlite")

    profile_a = store.create("user-a", "profile-a", title="A").copy()
    profile_b = store.create("user-a", "profile-b", title="B").copy()
    other_user = store.create("user-b", "profile-a", title="Other").copy()

    assert [item["conversation_id"] for item in store.list("user-a", "profile-a")] == [
        profile_a["conversation_id"]
    ]
    assert [item["conversation_id"] for item in store.list("user-a", "profile-b")] == [
        profile_b["conversation_id"]
    ]
    assert store.get("user-a", "profile-a", other_user["conversation_id"]) is None

    store.save_thread(
        "user-a",
        "profile-a",
        profile_a["conversation_id"],
        "provider-thread-a",
        provider_id="provider-1",
    )
    assert store.active("user-a", "profile-a")["conversation_id"] == profile_a["conversation_id"]
    assert store.active("user-a", "profile-b")["conversation_id"] == profile_b["conversation_id"]


def test_conversation_id_cannot_be_reassigned_to_another_profile(tmp_path):
    store = AgentConversationStore(tmp_path / "manager.sqlite")
    conversation = store.create("user-a", "profile-a")

    try:
        store.create(
            "user-a",
            "profile-b",
            conversation_id=conversation["conversation_id"],
        )
    except ValueError as error:
        assert "another Profile" in str(error)
    else:  # pragma: no cover - the ownership guard must reject the request
        raise AssertionError("conversation id was reassigned")

    assert store.get("user-a", "profile-a", conversation["conversation_id"]) is not None


def test_conversation_runtime_settings_are_isolated_and_persisted(tmp_path):
    store = AgentConversationStore(tmp_path / "manager.sqlite")
    first = store.create("user-a", "profile-a", title="First")
    second = store.create("user-a", "profile-a", title="Second")

    updated = store.update_runtime_settings(
        "user-a",
        "profile-a",
        first["conversation_id"],
        model_id="gpt-5.4",
        reasoning_effort="high",
        service_tier="fast",
    )

    assert updated["model_id"] == "gpt-5.4"
    assert updated["reasoning_effort"] == "high"
    assert updated["service_tier"] == "fast"
    untouched = store.get("user-a", "profile-a", second["conversation_id"])
    assert untouched["model_id"] == ""
    assert untouched["reasoning_effort"] == ""
    assert untouched["service_tier"] == ""


def test_conversation_runtime_observation_tracks_actual_model_and_context(tmp_path):
    store = AgentConversationStore(tmp_path / "manager.sqlite")
    conversation = store.create("user-a", "profile-a")

    updated = store.update_runtime_observation(
        "user-a",
        "profile-a",
        conversation["conversation_id"],
        actual_model="gpt-5.4-mini",
        model_context_window=200_000,
        total_tokens=42_000,
        last_tokens=1_200,
        compaction_count=1,
    )

    assert updated["actual_model"] == "gpt-5.4-mini"
    assert updated["model_context_window"] == 200_000
    assert updated["total_tokens"] == 42_000
    assert updated["last_tokens"] == 1_200
    assert updated["compaction_count"] == 1
