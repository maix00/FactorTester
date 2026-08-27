"""Research Graph HTTP methods for :class:`FactorTesterClient`."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchGraphClientMixin(ClientMixinBase):
    def list_profile_research(
        self,
        *,
        workspace_ref: str = "",
        lifecycle: str = "active",
        limit: int = 20,
        after: str = "",
    ) -> dict[str, Any]:
        """List owner-visible Work Packages, optionally filtering provenance."""
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
            "/api/catalog/research-graphs/versions",
            {"graph": graph},
        ))
        return dict(data.get("graph") or {})

    def list_research_graph_versions(
        self,
        graph_id: str,
    ) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(
            f"/api/catalog/research-graphs/{graph_id}/versions"
        ))
        return list(data.get("versions") or [])

    def get_active_research_graph(self, graph_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/catalog/research-graphs/{graph_id}/active"
        ))
        return dict(data.get("graph") or {})

    def download_research_graph_yaml(
        self,
        graph_id: str,
        version: int,
        *,
        locale: str = "",
    ) -> bytes:
        """Download one server graph version over the normal 7998 API.

        The graph is a small declarative input.  Factor/test source packages
        use the separate 7997 capability data plane and are never bundled by
        this method.
        """
        path = (
            f"/api/catalog/research-graphs/{graph_id}/versions/"
            f"{int(version)}/yaml"
            + (f"?locale={locale}" if locale else "")
        )
        return self.session.download(
            path,
            maximum_bytes=8 * 1024 * 1024,
        ).content

    def activate_research_graph(
        self,
        graph_id: str,
        version: int,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/catalog/research-graphs/{graph_id}/versions/"
            f"{version}/activate",
            {},
        ))
        return dict(data.get("graph") or {})

    def create_research_graph_instance(
        self,
        *,
        graph_id: str,
        product_group: str,
        workspace_id: str,
        capability_resolution: dict[str, Any],
        title: str = "",
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
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graph-instances/{instance_id}"
            f"/branches/{branch_id}/continuations",
            {
                "target_graph_version": target_graph_version,
                "job_id": job_id,
                "expected_target_hash": expected_target_hash,
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
        """Read compatibility state and candidate constraints for a Node.

        New local-first clients should load the graph YAML and decide the
        next edge locally; this method remains only for legacy projections
        and shared-report imports.
        """
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
