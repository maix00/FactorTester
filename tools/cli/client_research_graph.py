"""Research Graph HTTP methods for :class:`FactorTesterClient`."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchGraphClientMixin(ClientMixinBase):
    def get_active_research_runtime_budget_profile(
        self,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            "/api/research-runtime-budget-profiles/active"
        ))
        return dict(data.get("profile") or {})

    def get_research_graph_activation_preflight(
        self,
        graph_id: str,
        version: int,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graphs/{graph_id}/versions/{version}/activation"
        ))
        return dict(data.get("activation") or {})

    def activate_reviewed_research_graph(
        self,
        graph_id: str,
        version: int,
        *,
        approval_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/activation",
            {"approval_ref": approval_ref},
        ))
        return dict(data.get("activation") or {})

    def configure_research_runtime_budget_profile(
        self,
        *,
        ceiling_bytes: int,
        provider_id: str = "",
        model_id: str = "",
        tokenizer_id: str = "",
        tokenizer_revision: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-runtime-budget-profiles",
            {
                "ceiling_bytes": ceiling_bytes,
                "provider_id": provider_id,
                "model_id": model_id,
                "tokenizer_id": tokenizer_id,
                "tokenizer_revision": tokenizer_revision,
            },
        ))
        return dict(data.get("profile") or {})

    def list_profile_research(
        self,
        *,
        workspace_ref: str,
        lifecycle: str = "active",
        limit: int = 20,
        after: str = "",
    ) -> dict[str, Any]:
        """List one local Profile workspace's authorized research refs."""
        return self._expect_success(self.session.get(
            "/api/profile-research",
            query={
                "workspace_ref": workspace_ref,
                "lifecycle": lifecycle,
                "limit": limit,
                "after": after or None,
            },
        ))

    def get_profile_research(
        self,
        research_ref: str,
    ) -> dict[str, Any]:
        """Load one bounded current-state projection."""
        return self._expect_success(self.session.get(
            f"/api/profile-research/{research_ref}"
        ))

    def transition_profile_research_lifecycle(
        self,
        work_package_ref: str,
        *,
        target: str,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.patch(
            f"/api/profile-research/{work_package_ref}/lifecycle",
            {
                "target": target,
                "expected_revision": expected_revision,
                "reason": reason,
            },
        ))

    def get_profile_research_branch(
        self,
        work_package_ref: str,
        branch_id: str,
    ) -> dict[str, Any]:
        """Load one Hypothesis Branch under a Work Package."""
        return self._expect_success(self.session.get(
            f"/api/profile-research/{work_package_ref}/branches/{branch_id}"
        ))

    def get_profile_research_report_carrier(
        self,
        work_package_ref: str,
        branch_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Read one trusted historical Carrier without changing research state."""
        return self._expect_success(self.session.get(
            f"/api/profile-research/{work_package_ref}/branches/{branch_id}/"
            f"checkpoints/{trace_id}/report-carrier"
        ))

    def list_profile_research_branch_timeline(
        self,
        work_package_ref: str,
        branch_id: str,
        *,
        limit: int = 50,
        after: str = "",
    ) -> dict[str, Any]:
        """Page one Hypothesis Branch timeline."""
        return self._expect_success(self.session.get(
            f"/api/profile-research/{work_package_ref}/branches/"
            f"{branch_id}/timeline",
            query={
                "limit": limit,
                "after": after or None,
            },
        ))

    def list_profile_research_timeline(
        self,
        research_ref: str,
        *,
        limit: int = 50,
        after: str = "",
    ) -> dict[str, Any]:
        """Page compact transition refs without replaying evidence history."""
        return self._expect_success(self.session.get(
            f"/api/profile-research/{research_ref}/timeline",
            query={
                "limit": limit,
                "after": after or None,
            },
        ))

    def publish_research_graph(self, graph: dict[str, Any]) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-graphs/versions",
            {"graph": graph},
        ))
        return dict(data.get("graph") or {})

    def revise_unused_research_graph_draft(
        self,
        graph: dict[str, Any],
    ) -> dict[str, Any]:
        graph_id = str(graph.get("graph_id") or "")
        version = int(graph.get("version") or 0)
        data = self._expect_success(self.session.put(
            f"/api/research-graphs/{graph_id}/versions/{version}/unused-draft",
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
        title: str = "",
        shadow_graph_version: int | None = None,
        shadow_run_id: str = "",
        shadow_proposal_id: str = "",
        profile_ref: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-graph-instances",
            {
                "graph_id": graph_id,
                "product_group": product_group,
                "workspace_id": workspace_id,
                "capability_resolution": capability_resolution,
                "title": title,
                "shadow_graph_version": shadow_graph_version,
                "shadow_run_id": shadow_run_id,
                "shadow_proposal_id": shadow_proposal_id,
                "profile_ref": profile_ref,
            },
        ))
        return dict(data.get("instance") or {})

    def fork_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
        *,
        label: str,
        acting_profile_ref: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/fork",
            {"label": label, "acting_profile_ref": acting_profile_ref},
        ))
        return dict(data.get("branch") or {})

    def handoff_research_graph_branch(
        self,
        instance_id: str,
        branch_id: str,
        *,
        source_profile_ref: str,
        destination_profile_ref: str,
        expected_checkpoint_ref: str,
        expected_checkpoint_hash: str,
        authorization_ref: str,
        source_display_name: str = "",
        destination_display_name: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/handoff",
            {
                "source_profile_ref": source_profile_ref,
                "destination_profile_ref": destination_profile_ref,
                "expected_checkpoint_ref": expected_checkpoint_ref,
                "expected_checkpoint_hash": expected_checkpoint_hash,
                "authorization_ref": authorization_ref,
                "source_display_name": source_display_name,
                "destination_display_name": destination_display_name,
            },
        ))
        return dict(data.get("handoff") or {})

    def preview_research_graph_continuation(
        self,
        instance_id: str,
        branch_id: str,
        *,
        target_graph_version: int,
        job_id: str,
        execution_mode: str = "live",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/continuation-preview",
            {
                "target_graph_version": target_graph_version,
                "job_id": job_id,
                "execution_mode": execution_mode,
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
        execution_mode: str = "live",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/continuations",
            {
                "target_graph_version": target_graph_version,
                "job_id": job_id,
                "expected_target_hash": expected_target_hash,
                "execution_mode": execution_mode,
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

    def get_research_graph_node_info(
        self,
        instance_id: str,
        branch_id: str,
    ) -> dict[str, Any]:
        """Read the current Node contract and its ordered next actions."""
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/node"
        ))
        return dict(data.get("node") or {})

    def get_research_graph_edge_info(
        self,
        instance_id: str,
        branch_id: str,
        edge_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/edges/{edge_id}"
        ))
        return dict(data.get("edge") or {})

    def get_current_graph_requirement(
        self,
        instance_id: str,
        branch_id: str,
        requirement_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/requirements/{requirement_id}"
        ))
        return dict(data.get("requirement") or {})

    def append_current_report_checkpoint(
        self,
        instance_id: str,
        branch_id: str,
        *,
        node_id: str,
        report_submission: dict[str, Any],
        report_artifact_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/current-report-checkpoints",
            {
                "node_id": node_id,
                "report_submission": report_submission,
                "report_artifact_ref": report_artifact_ref,
            },
        ))
        return dict(data.get("checkpoint") or {})

    def get_result_report_projection(
        self,
        instance_id: str,
        branch_id: str,
        *,
        action_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/result-report-projection",
            query={"action_id": action_id},
        ))
        return dict(data.get("projection") or {})

    def backfill_result_audit(
        self, instance_id: str, branch_id: str, *,
        audited_checkpoint: dict[str, Any],
        proposal: dict[str, Any], decision: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/result-audit-backfills",
            {
                "audited_checkpoint": audited_checkpoint,
                "proposal": proposal,
                "decision": decision,
            },
        ))
        return dict(data.get("receipt") or {})

    def get_research_cycle_object(
        self,
        instance_id: str,
        branch_id: str,
        object_type: str,
        object_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/cycle-objects/{object_type}/{object_id}",
            query={"trace_id": trace_id} if trace_id else None,
        ))
        return dict(data.get("object") or {})

    def get_trial_execution_checkpoint(
        self,
        instance_id: str,
        branch_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/trial-execution-checkpoint"
        ))
        return dict(data.get("execution") or {})

    def operate_trial_execution_checkpoint(
        self,
        instance_id: str,
        branch_id: str,
        *,
        expected_latest_trace_id: str,
        expected_checkpoint_hash: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/trial-execution-checkpoint/operations",
            {
                "expected_latest_trace_id": expected_latest_trace_id,
                "expected_checkpoint_hash": expected_checkpoint_hash,
                "operation": operation,
                "payload": payload or {},
            },
        ))
        return dict(data.get("result") or {})

    def recover_trial_execution_checkpoint(
        self,
        instance_id: str,
        branch_id: str,
        *,
        expected_latest_trace_id: str,
        expected_execution_node: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/trial-execution-checkpoint/recover",
            {
                "expected_latest_trace_id": expected_latest_trace_id,
                "expected_execution_node": expected_execution_node,
            },
        ))
        return dict(data.get("recovery") or {})

    def get_trial_execution_binding(
        self,
        instance_id: str,
        branch_id: str,
        *,
        run_spec_hash: str,
        trial_role: str,
        comparison_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/trial-execution-binding",
            query={
                "run_spec_hash": run_spec_hash,
                "trial_role": trial_role,
                "comparison_id": comparison_id,
            },
        ))
        return dict(data.get("trial_binding") or {})

    def revise_trial_plan(
        self,
        instance_id: str,
        branch_id: str,
        *,
        expected_latest_trace_id: str,
        expected_checkpoint_hash: str,
        expected_trial_plan_hash: str,
        trial_plan: dict[str, Any],
        acting_profile_ref: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/trial-plan/revisions",
            {
                "expected_latest_trace_id": expected_latest_trace_id,
                "expected_checkpoint_hash": expected_checkpoint_hash,
                "expected_trial_plan_hash": expected_trial_plan_hash,
                "trial_plan": trial_plan,
                "acting_profile_ref": acting_profile_ref,
            },
        ))
        return dict(data.get("revision") or {})

    def advance_research_graph_node(
        self,
        instance_id: str,
        branch_id: str,
        *,
        edge_id: str,
        evidence: dict[str, Any],
        acting_profile_ref: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/node/advance",
            {
                "edge_id": edge_id,
                "evidence": evidence,
                "acting_profile_ref": acting_profile_ref,
            },
        ))
        return dict(data.get("branch") or {})
