"""Project authoritative app-server runtime events into conversation metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.manager.storage.agent_conversation_store import AgentConversationStore


class AgentConversationRuntimeObserver:
    """Persist small runtime observations without mirroring conversation content."""

    def __init__(
        self,
        store: AgentConversationStore,
        principal: str,
        profile_id: str,
    ) -> None:
        self.store = store
        self.principal = str(principal or "").strip()
        self.profile_id = str(profile_id or "").strip()
        self._compactions: set[tuple[str, str]] = set()

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _thread_id(params: Mapping[str, object]) -> str:
        return str(params.get("threadId") or params.get("thread_id") or "").strip()

    def observe(self, payload: Mapping[str, Any]) -> None:
        method = str(payload.get("method") or payload.get("type") or "").strip()
        params = self._mapping(payload.get("params"))
        thread_id = self._thread_id(params)
        if not thread_id:
            return
        conversation = self.store.get_by_provider_thread(
            self.principal, self.profile_id, thread_id,
        )
        if conversation is None:
            return
        conversation_id = str(conversation["conversation_id"])
        if method == "thread/tokenUsage/updated":
            usage = self._mapping(params.get("tokenUsage"))
            last = self._mapping(usage.get("last"))
            total = self._mapping(usage.get("total"))
            self.store.update_runtime_observation(
                self.principal,
                self.profile_id,
                conversation_id,
                model_context_window=int(usage.get("modelContextWindow") or 0),
                total_tokens=int(total.get("totalTokens") or 0),
                last_tokens=int(last.get("totalTokens") or 0),
            )
            return
        if method == "thread/settings/updated":
            settings = self._mapping(params.get("threadSettings"))
            model = str(settings.get("model") or "").strip()
            if model:
                self.store.update_runtime_observation(
                    self.principal,
                    self.profile_id,
                    conversation_id,
                    actual_model=model,
                )
            return
        if method == "model/rerouted":
            model = str(params.get("toModel") or "").strip()
            if model:
                self.store.update_runtime_observation(
                    self.principal,
                    self.profile_id,
                    conversation_id,
                    actual_model=model,
                )
            return
        if method != "thread/compacted":
            return
        event_key = (thread_id, str(params.get("turnId") or "").strip())
        if event_key in self._compactions:
            return
        self._compactions.add(event_key)
        self.store.increment_compaction(
            self.principal, self.profile_id, conversation_id,
        )

