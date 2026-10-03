"""Agent Flow HTTP methods for :class:`FactorTesterClient`."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class AgentFlowClientMixin(ClientMixinBase):
    def resume_agent(
        self,
        agent_id: str,
        *,
        role: str,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": role}
        if role in {"planning", "research"}:
            payload["workspace_id"] = workspace_id
        data = self._expect_success(self.session.post(
            f"/api/agent-flow/agents/{agent_id}/resume",
            payload,
        ))
        return dict(data.get("resume") or {})

    def register_agent_execution(
        self,
        *,
        execution_id: str,
        agent_id: str,
        actor_role: str,
        authority_scope: str,
        purpose: str,
        agent_principal_hash: str,
        lineage_hash: str,
        task_ref: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-agent-executions",
            {
                "execution_id": execution_id,
                "agent_id": agent_id,
                "actor_role": actor_role,
                "authority_scope": authority_scope,
                "task_ref": task_ref,
                "purpose": purpose,
                "agent_principal_hash": agent_principal_hash,
                "lineage_hash": lineage_hash,
            },
        ))
        return dict(data.get("execution") or {})
