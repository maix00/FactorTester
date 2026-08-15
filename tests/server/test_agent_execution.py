from __future__ import annotations

import pytest

from server.services.agent_execution.store import AgentExecutionStore


def _register(store: AgentExecutionStore, **overrides):
    values = {
        "owner_user_id": "alice",
        "execution_id": "execution-1",
        "agent_id": "research-agent",
        "actor_role": "researcher",
        "authority_scope": "local_research",
        "task_ref": "work-package-1",
        "purpose": "propose a graph change",
        "agent_principal_hash": "a" * 64,
        "lineage_hash": "b" * 64,
    }
    values.update(overrides)
    return store.register_execution(**values)


def test_execution_store_persists_only_graph_identity(tmp_path) -> None:
    store = AgentExecutionStore(tmp_path / "execution.sqlite")

    execution = _register(store)
    loaded = store.load_execution(
        owner_user_id="alice",
        execution_id="execution-1",
    )

    assert loaded == execution
    assert set(execution) == {
        "execution_id",
        "owner_user_id",
        "agent_id",
        "actor_role",
        "authority_scope",
        "task_ref",
        "purpose",
        "agent_principal_hash",
        "lineage_hash",
        "created_at",
    }
    assert not {
        "token_limit",
        "input_tokens",
        "output_tokens",
        "status",
        "provider_id",
    } & set(execution)


def test_execution_store_is_idempotent_but_rejects_identity_drift(tmp_path) -> None:
    store = AgentExecutionStore(tmp_path / "execution.sqlite")

    first = _register(store)
    assert _register(store) == first

    with pytest.raises(ValueError, match="does not match"):
        _register(store, purpose="different purpose")


def test_execution_store_loads_only_requested_owner_executions(tmp_path) -> None:
    store = AgentExecutionStore(tmp_path / "execution.sqlite")
    _register(store)
    _register(
        store,
        execution_id="execution-2",
        owner_user_id="bob",
    )

    assert set(store.load_executions(
        owner_user_id="alice",
        execution_ids=["execution-1", "execution-2"],
    )) == {"execution-1"}
