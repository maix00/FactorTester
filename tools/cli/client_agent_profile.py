"""Typed HTTP methods for runtime-scoped Profile Agent ownership."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class AgentProfileClientMixin(ClientMixinBase):
    """Keep client and server Profile runtime operations explicit."""

    def list_agent_models(
        self,
        *,
        runtime_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        query = {"runtime_kind": runtime_kind} if runtime_kind else None
        data = self._expect_success(
            self.session.get("/api/client/agent-models", query=query),
        )
        return [item for item in data.get("providers") or [] if isinstance(item, dict)]

    def save_agent_model(self, provider: dict[str, Any]) -> dict[str, Any]:
        data = self._expect_success(
            self.session.post("/api/client/agent-models", provider),
        )
        return dict(data.get("provider") or {})

    def delete_agent_model(self, provider_id: str) -> bool:
        data = self._expect_success(
            self.session.delete(
                f"/api/client/agent-models/{provider_id}",
            ),
        )
        return bool(data.get("deleted"))

    def list_profile_agent_runtime(self) -> dict[str, Any]:
        return self._expect_success(
            self.session.get("/api/client/agent-runtime"),
        )

    def bind_profile_runtime(
        self,
        profile_id: str,
        *,
        runtime_kind: str,
        executor_id: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(
            self.session.post(
                "/api/client/profile-runtime",
                {
                    "profile_id": profile_id,
                    "runtime_kind": runtime_kind,
                    "executor_id": executor_id,
                },
            ),
        )
        return dict(data.get("runtime") or {})

    def claim_profile_agent(
        self,
        profile_id: str,
        *,
        provider_id: str,
        agent_id: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-claims",
                {
                    "profile_id": profile_id,
                    "provider_id": provider_id,
                    "agent_id": agent_id,
                },
            ),
        )

    def heartbeat_profile_agent(
        self,
        claim_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-claims/heartbeat",
                {
                    "claim_id": claim_id,
                    "agent_id": agent_id,
                },
            ),
        )

    def release_profile_agent(
        self,
        claim_id: str,
        *,
        agent_id: str = "",
        force: bool = False,
    ) -> bool:
        data = self._expect_success(
            self.session.post(
                "/api/client/profile-claims/release",
                {
                    "claim_id": claim_id,
                    "agent_id": agent_id,
                    "force": bool(force),
                },
            ),
        )
        return bool(data.get("released"))

    def profile_agent_status(self, profile_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent",
                query={"profile_id": profile_id},
            )
        )

    def list_profile_agent_models(
        self,
        profile_id: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent/models",
                query={
                    "profile_id": profile_id,
                    "refresh": "1" if refresh else "0",
                },
            )
        )

    def list_profile_agent_conversations(
        self,
        profile_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent/conversations",
                query={"profile_id": profile_id},
            )
        )

    def update_profile_agent_conversation_settings(
        self,
        profile_id: str,
        conversation_id: str,
        *,
        model_id: str,
        reasoning_effort: str = "",
        service_tier: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/conversations/settings",
                {
                    "profile_id": profile_id,
                    "conversation_id": conversation_id,
                    "model_id": model_id,
                    "reasoning_effort": reasoning_effort,
                    "service_tier": service_tier,
                },
            )
        )

    def start_profile_agent(self, profile_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/start",
                {"profile_id": profile_id},
            )
        )

    def stop_profile_agent(self, profile_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/stop",
                {"profile_id": profile_id},
            )
        )

    def inspect_profile_agent_assistance(self, profile_id: str, *, tab_id: str = "") -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent/assistance",
                query={"profile_id": profile_id, **({"tab_id": tab_id} if tab_id else {})},
            )
        )

    def validate_profile_agent_assistance(
        self,
        profile_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/assistance/validate",
                {"profile_id": profile_id, "draft_id": draft_id},
            )
        )

    def apply_profile_agent_assistance(
        self,
        profile_id: str,
        *,
        draft_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/assistance/apply",
                {
                    "profile_id": profile_id,
                    "draft_id": draft_id,
                },
            )
        )

    def create_profile_agent_assistance_draft(
        self,
        profile_id: str,
        document: dict[str, Any] | None = None,
        *,
        from_current: bool = False,
        tab_id: str = "",
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/assistance/drafts",
                {
                    "profile_id": profile_id,
                    "document": document,
                    "from_current": from_current,
                    **({"tab_id": tab_id} if tab_id else {}),
                },
            )
        )

    def patch_profile_agent_assistance_draft(
        self,
        profile_id: str,
        draft_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/api/client/profile-agent/assistance/drafts/patch",
                {"profile_id": profile_id, "draft_id": draft_id, "patch": patch},
            )
        )

    def list_profile_agent_assistance_drafts(self, profile_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent/assistance/drafts",
                query={"profile_id": profile_id},
            )
        )

    def get_profile_agent_assistance_draft(
        self,
        profile_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(
                "/api/client/profile-agent/assistance/drafts",
                query={"profile_id": profile_id, "draft_id": draft_id},
            )
        )

    def delete_profile_agent_assistance_draft(
        self,
        profile_id: str,
        draft_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.delete(
                "/api/client/profile-agent/assistance/drafts",
                query={"profile_id": profile_id, "draft_id": draft_id},
            )
        )
