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
            self.session.post("/api/client/profile-runtime", {
                "profile_id": profile_id,
                "runtime_kind": runtime_kind,
                "executor_id": executor_id,
            }),
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
            self.session.post("/api/client/profile-claims", {
                "profile_id": profile_id,
                "provider_id": provider_id,
                "agent_id": agent_id,
            }),
        )

    def heartbeat_profile_agent(
        self,
        claim_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/api/client/profile-claims/heartbeat", {
                "claim_id": claim_id,
                "agent_id": agent_id,
            }),
        )

    def release_profile_agent(
        self,
        claim_id: str,
        *,
        agent_id: str = "",
        force: bool = False,
    ) -> bool:
        data = self._expect_success(
            self.session.post("/api/client/profile-claims/release", {
                "claim_id": claim_id,
                "agent_id": agent_id,
                "force": bool(force),
            }),
        )
        return bool(data.get("released"))
