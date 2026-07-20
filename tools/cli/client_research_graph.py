"""Research Graph HTTP methods for :class:`FactorTesterClient`."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchGraphClientMixin(ClientMixinBase):
    def publish_research_graph(self, graph: dict[str, Any]) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-graphs/versions",
            {"graph": graph},
        ))
        return dict(data.get("graph") or {})

    def list_research_graph_versions(
        self,
        graph_id: str,
    ) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(
            f"/api/research-graphs/{graph_id}/versions"
        ))
        return list(data.get("versions") or [])

    def get_active_research_graph(self, graph_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graphs/{graph_id}/active"
        ))
        return dict(data.get("graph") or {})

    def validate_research_graph(
        self,
        graph_id: str,
        version: int,
        evidence: dict[str, Any],
        *,
        proposal_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/validation",
            {**evidence, "proposal_id": proposal_id},
        ))
        return dict(data.get("validation") or {})

    def propose_research_graph(
        self,
        graph_id: str,
        version: int,
        *,
        risk_level: str,
        change_diff: dict[str, Any],
        evidence_refs: list[str],
        token_estimate: int,
        agent_execution_id: str,
        conversation_ref: str,
        pointer_action: str = "activate_graph",
        pointer_from_version: int = 0,
        pointer_reason: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/proposals",
            {
                "risk_level": risk_level,
                "change_diff": change_diff,
                "evidence_refs": evidence_refs,
                "token_estimate": token_estimate,
                "agent_execution_id": agent_execution_id,
                "conversation_ref": conversation_ref,
                "pointer_action": pointer_action,
                "pointer_from_version": pointer_from_version,
                "pointer_reason": pointer_reason,
            },
        ))
        return dict(data.get("proposal") or {})

    def review_research_graph_proposal(
        self,
        proposal_id: str,
        *,
        disposition: str,
        scope_drift: bool,
        semantic_uncertainty: bool,
        evidence_refs: list[str],
        agent_execution_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-proposals/{proposal_id}/reviews",
            {
                "disposition": disposition,
                "scope_drift": scope_drift,
                "semantic_uncertainty": semantic_uncertainty,
                "evidence_refs": evidence_refs,
                "agent_execution_id": agent_execution_id,
            },
        ))
        return dict(data.get("review") or {})

    def audit_research_graph(
        self,
        graph_id: str,
        version: int,
        *,
        proposal_id: str,
        disposition: str,
        grill_evidence: list[dict[str, Any]],
        grill_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/audit",
            {
                "proposal_id": proposal_id,
                "disposition": disposition,
                "grill_evidence": grill_evidence,
                "grill_ref": grill_ref,
            },
        ))
        return dict(data.get("audit") or {})

    def activate_research_graph(
        self,
        graph_id: str,
        version: int,
        *,
        human_authorization_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/activate",
            {"human_authorization_id": human_authorization_id},
        ))
        return dict(data.get("graph") or {})

    def authorize_research_graph_activation(
        self,
        *,
        graph_id: str,
        graph_version: int,
        proposal_id: str,
        graph_hash: str,
        diff_hash: str,
        conversation_ref: str,
        approval_ref: str,
        pointer_action: str = "activate_graph",
        pointer_from_version: int = 0,
        pointer_reason: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-human-activation-authorizations",
            {
                "graph_id": graph_id,
                "graph_version": graph_version,
                "proposal_id": proposal_id,
                "graph_hash": graph_hash,
                "diff_hash": diff_hash,
                "conversation_ref": conversation_ref,
                "approval_ref": approval_ref,
                "pointer_action": pointer_action,
                "pointer_from_version": pointer_from_version,
                "pointer_reason": pointer_reason,
            },
        ))
        return dict(data.get("authorization") or {})

    def rollback_research_graph(
        self,
        graph_id: str,
        *,
        target_version: int,
        reason: str,
        human_authorization_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/rollback",
            {
                "target_version": target_version,
                "reason": reason,
                "human_authorization_id": human_authorization_id,
            },
        ))
        return dict(data.get("rollback") or {})

    def create_research_graph_instance(
        self,
        *,
        graph_id: str,
        product_group: str,
        workspace_id: str,
        capability_resolution: dict[str, Any],
        shadow_graph_version: int | None = None,
        shadow_run_id: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-graph-instances",
            {
                "graph_id": graph_id,
                "product_group": product_group,
                "workspace_id": workspace_id,
                "capability_resolution": capability_resolution,
                "shadow_graph_version": shadow_graph_version,
                "shadow_run_id": shadow_run_id,
            },
        ))
        return dict(data.get("instance") or {})

    def fork_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
        *,
        label: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/fork",
            {"label": label},
        ))
        return dict(data.get("branch") or {})

    def preview_research_graph_continuation(
        self,
        instance_id: str,
        branch_id: str,
        *,
        target_graph_version: int,
        job_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/continuation-preview",
            {
                "target_graph_version": target_graph_version,
                "job_id": job_id,
            },
        ))
        return dict(data.get("preview") or {})

    def continue_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
        *,
        target_graph_version: int,
        job_id: str,
        expected_target_hash: str,
        human_authorization_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/continuations",
            {
                "target_graph_version": target_graph_version,
                "job_id": job_id,
                "expected_target_hash": expected_target_hash,
                "human_authorization_id": human_authorization_id,
            },
        ))
        return dict(data.get("instance") or {})

    def get_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}"
        ))
        return dict(data.get("branch") or {})

    def get_research_graph_branch_context(
        self,
        instance_id: str,
        branch_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/context"
        ))
        return dict(data.get("context") or {})

    def get_research_graph_branch_next(
        self,
        instance_id: str,
        branch_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/next"
        ))
        return dict(data.get("next") or {})

    def get_research_cycle_object(
        self,
        instance_id: str,
        branch_id: str,
        object_type: str,
        object_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/cycle-objects/{object_type}/{object_id}"
        ))
        return dict(data.get("object") or {})

    def advance_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
        *,
        edge_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/advance",
            {"edge_id": edge_id, "evidence": evidence},
        ))
        return dict(data.get("branch") or {})
