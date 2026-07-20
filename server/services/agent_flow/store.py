"""Unified public Interface for provider-neutral Agent Flow persistence."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any

import settings as Settings

from .budget_periods import BudgetPeriods
from .invocations import InvocationLifecycle
from .queries import AgentFlowQueries
from .schema import ensure_schema
from .validation import CHARGING_POLICY_VERSION


# Kept as a module alias while the offline migration remains internal.
_CHARGING_POLICY_VERSION = CHARGING_POLICY_VERSION
_STORE_CACHE: dict[str, AgentFlowStore] = {}


class AgentFlowStore:
    """One stable Seam over budget, invocation, and query Modules."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self.ensure_schema()
        self._budgets = BudgetPeriods(self.db_path)
        self._invocations = InvocationLifecycle(
            self.db_path,
            self._budgets,
        )
        self._queries = AgentFlowQueries(self.db_path)

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if not self._schema_ready:
                ensure_schema(self.db_path)
                self._schema_ready = True

    def reserve_invocation(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        actor_role: str,
        authority_scope: str,
        purpose: str,
        runtime_id: str,
        model_id: str,
        max_input_tokens: int,
        max_output_tokens: int,
        agent_principal_hash: str,
        lineage_hash: str,
        sponsor_agent_id: str = "",
        task_ref: str = "",
        input_hash: str = "",
        context_cost: dict[str, int] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        return self._invocations.reserve_invocation(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            actor_role=actor_role,
            authority_scope=authority_scope,
            purpose=purpose,
            runtime_id=runtime_id,
            model_id=model_id,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            agent_principal_hash=agent_principal_hash,
            lineage_hash=lineage_hash,
            sponsor_agent_id=sponsor_agent_id,
            task_ref=task_ref,
            input_hash=input_hash,
            context_cost=context_cost,
            idempotency_key=idempotency_key,
        )

    def configure_token_limit(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int,
    ) -> dict[str, Any]:
        return self._budgets.configure_token_limit(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            token_limit=token_limit,
        )

    def reset_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        token_limit: int | None = None,
    ) -> dict[str, Any]:
        return self._budgets.reset_budget_period(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            token_limit=token_limit,
        )

    def list_budget_periods(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> list[dict[str, Any]]:
        return self._budgets.list_budget_periods(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )

    def load_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        return self._queries.load_invocation(
            owner_user_id=owner_user_id,
            invocation_id=invocation_id,
        )

    def load_invocations(
        self,
        *,
        owner_user_id: str,
        invocation_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        return self._queries.load_invocations(
            owner_user_id=owner_user_id,
            invocation_ids=invocation_ids,
        )

    def count_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> int:
        return self._queries.count_invocations(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )

    def count_subagent_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> int:
        return self._queries.count_invocations(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            subagents_only=True,
        )

    def settled_tokens_for_invocations(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        invocation_ids: list[str],
    ) -> int:
        return self._queries.settled_tokens_for_invocations(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            invocation_ids=invocation_ids,
        )

    def release_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
    ) -> dict[str, Any]:
        return self._invocations.release_invocation(
            owner_user_id=owner_user_id,
            invocation_id=invocation_id,
        )

    def settle_invocation(
        self,
        *,
        owner_user_id: str,
        invocation_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int = 0,
        provider_request_id: str = "",
        provider_attestation: str = "",
    ) -> dict[str, Any]:
        return self._invocations.settle_invocation(
            owner_user_id=owner_user_id,
            invocation_id=invocation_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            provider_request_id=provider_request_id,
            provider_attestation=provider_attestation,
        )

    def load_current_budget_period(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
    ) -> dict[str, Any] | None:
        return self._budgets.load_current_budget_period(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
        )


def database_path() -> Path:
    configured = os.environ.get("AGENT_FLOW_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    cache_path = Path(Settings.CACHE_DB_PATH)
    return cache_path.with_name(
        f"{cache_path.stem}.agent-flow{cache_path.suffix or '.sqlite'}"
    )


def get_store() -> AgentFlowStore:
    path = str(database_path())
    store = _STORE_CACHE.get(path)
    if store is None:
        store = AgentFlowStore(path)
        _STORE_CACHE[path] = store
    return store


def clear_store_cache() -> None:
    _STORE_CACHE.clear()
