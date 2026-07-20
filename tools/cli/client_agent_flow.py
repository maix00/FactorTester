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
        instance_id: str = "",
        branch_id: str = "",
        workspace_id: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": role}
        if role == "research":
            payload.update({
                "instance_id": instance_id,
                "branch_id": branch_id,
            })
        elif role == "planning":
            payload["workspace_id"] = workspace_id
        data = self._expect_success(self.session.post(
            f"/api/agent-flow/agents/{agent_id}/resume",
            payload,
        ))
        return dict(data.get("resume") or {})

    def load_agent_budget_period(self, agent_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/agent-flow/agents/{agent_id}/budget"
        ))
        return dict(data.get("budget_period") or {})

    def configure_agent_budget_period(
        self,
        agent_id: str,
        *,
        token_limit: int,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.put(
            f"/api/agent-flow/agents/{agent_id}/budget",
            {"token_limit": token_limit},
        ))
        return dict(data.get("budget_period") or {})

    def reset_agent_budget_period(
        self,
        agent_id: str,
        *,
        token_limit: int | None = None,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/agent-flow/agents/{agent_id}/budget/reset",
            {"token_limit": token_limit},
        ))
        return dict(data.get("budget_period") or {})

    def reserve_agent_invocation(
        self,
        *,
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
        data = self._expect_success(self.session.post(
            "/api/agent-flow/invocations",
            {
                "agent_id": agent_id,
                "sponsor_agent_id": sponsor_agent_id,
                "actor_role": actor_role,
                "authority_scope": authority_scope,
                "task_ref": task_ref,
                "purpose": purpose,
                "runtime_id": runtime_id,
                "model_id": model_id,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "agent_principal_hash": agent_principal_hash,
                "lineage_hash": lineage_hash,
                "input_hash": input_hash,
                "context_cost": context_cost or {},
                "idempotency_key": idempotency_key,
            },
        ))
        return dict(data.get("invocation") or {})

    def settle_agent_invocation(
        self,
        invocation_id: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int = 0,
        provider_request_id: str = "",
        provider_attestation: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/agent-flow/invocations/{invocation_id}/settle",
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "provider_request_id": provider_request_id,
                "provider_attestation": provider_attestation,
            },
        ))
        return dict(data.get("invocation") or {})

    def release_agent_invocation(
        self,
        invocation_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/agent-flow/invocations/{invocation_id}/release",
            {},
        ))
        return dict(data.get("invocation") or {})
