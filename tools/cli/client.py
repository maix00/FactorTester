"""High-level FactorTester HTTP API client."""

from __future__ import annotations

from typing import Any

from .http import HttpSession


class FactorTesterClient:
    def __init__(self, session: HttpSession) -> None:
        self.session = session

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._expect_success(self.session.post("/login", {"username": username, "password": password}))

    def set_keep_login(self, enabled: bool) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/api/keep_login", {"keep_login": bool(enabled)})
        )

    def logout(self) -> dict[str, Any]:
        try:
            return self._expect_success(self.session.post("/logout", {}))
        finally:
            self.session.clear_cookies()

    def create_workspace(
        self,
        *,
        factor_families: list[dict[str, Any]] | None = None,
        factors: list[dict[str, Any]] | None = None,
        title: str = "Factor research",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post("/api/workspaces", {
            "title": title,
            "factor_families": factor_families or [],
            "factors": factors or [],
        }))
        return dict(data.get("workspace") or {})

    def list_workspaces(self) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get("/api/workspaces"))
        return list(data.get("workspaces") or [])

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/workspaces/{workspace_id}"))
        return dict(data.get("workspace") or {})

    def get_workspace_configuration(self, workspace_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/workspaces/{workspace_id}/configuration"))
        return dict(data.get("configuration") or {})

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
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/validation",
            evidence,
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
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/proposals",
            {
                "risk_level": risk_level,
                "change_diff": change_diff,
                "evidence_refs": evidence_refs,
                "token_estimate": token_estimate,
                "agent_execution_id": agent_execution_id,
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

    def create_research_agent_execution(
        self,
        *,
        actor_role: str,
        model_id: str = "",
        codex_version: str = "",
        reservation_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-agent-executions",
            {
                "actor_role": actor_role,
                "model_id": model_id,
                "codex_version": codex_version,
                "reservation_id": reservation_id,
            },
        ))
        return dict(data.get("execution") or {})

    def create_research_token_budget(
        self,
        *,
        scope_id: str,
        token_limit: int,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-token-budgets",
            {"scope_id": scope_id, "token_limit": token_limit},
        ))
        return dict(data.get("budget") or {})

    def reserve_research_tokens(
        self,
        scope_id: str,
        *,
        work_kind: str,
        max_input_tokens: int,
        max_output_tokens: int,
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-token-budgets/{scope_id}/reserve",
            {
                "work_kind": work_kind,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "ttl_seconds": ttl_seconds,
            },
        ))
        return dict(data.get("reservation") or {})

    def commit_research_tokens(
        self,
        reservation_id: str,
        *,
        provider_receipt_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-token-reservations/{reservation_id}/commit",
            {"provider_receipt_id": provider_receipt_id},
        ))
        return dict(data.get("commit") or {})

    def release_research_tokens(
        self,
        reservation_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-token-reservations/{reservation_id}/release",
            {},
        ))
        return dict(data.get("release") or {})

    def audit_research_graph(
        self,
        graph_id: str,
        version: int,
        *,
        disposition: str,
        grill_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/audit",
            {
                "disposition": disposition,
                "grill_evidence": grill_evidence,
            },
        ))
        return dict(data.get("audit") or {})

    def activate_research_graph(
        self,
        graph_id: str,
        version: int,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/versions/{version}/activate",
            {},
        ))
        return dict(data.get("graph") or {})

    def rollback_research_graph(
        self,
        graph_id: str,
        *,
        target_version: int,
        reason: str,
        grill_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-graphs/{graph_id}/rollback",
            {
                "target_version": target_version,
                "reason": reason,
                "grill_evidence": grill_evidence,
            },
        ))
        return dict(data.get("rollback") or {})

    def create_research_graph_instance(
        self,
        *,
        graph_id: str,
        product_group: str,
        workspace_id: str,
        capability_receipt: dict[str, Any],
        token_budget: int | None = None,
        shadow_graph_version: int | None = None,
        shadow_run_id: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-graph-instances",
            {
                "graph_id": graph_id,
                "product_group": product_group,
                "workspace_id": workspace_id,
                "capability_receipt": capability_receipt,
                "token_budget": token_budget,
                "shadow_graph_version": shadow_graph_version,
                "shadow_run_id": shadow_run_id,
            },
        ))
        return dict(data.get("instance") or {})

    def approve_research_capability(
        self,
        *,
        capability_id: str,
        descriptor_hash: str,
        product_group: str,
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-capability-approvals",
            {
                "capability_id": capability_id,
                "descriptor_hash": descriptor_hash,
                "product_group": product_group,
                "evidence_refs": evidence_refs,
            },
        ))
        return dict(data.get("approval") or {})

    def attest_research_capabilities(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-capability-receipts",
            payload,
        ))
        return dict(data.get("receipt") or {})

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

    def validate_external_factor_artifact(self, manifest_path: str) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/external-factor-artifacts/validate",
            {"manifest_path": manifest_path},
        ))
        return dict(data.get("artifact") or {})

    def save_configuration_template(self, workspace_id: str, *, name: str) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/workspaces/{workspace_id}/configuration/templates",
            {"name": name},
        ))
        return dict(data.get("template") or {})

    def update_workspace_configuration(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(
            self.session.put(f"/api/workspaces/{workspace_id}/configuration", {
            "expected_revision": expected_revision,
            "payload": payload,
            })
        )
        return dict(data.get("configuration") or {})

    def load_configuration_template(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        configuration_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/workspaces/{workspace_id}/configuration/load-template",
            {"expected_revision": expected_revision, "configuration_id": configuration_id},
        ))
        return dict(data.get("configuration") or {})

    def list_configuration_templates(self) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get("/api/configuration-templates"))
        return list(data.get("templates") or [])

    def submit_run(
        self,
        workspace_id: str,
        configuration_revision: int,
        *,
        analyses: list[str],
        retention_mode: str = "summary",
        step_mode: bool = False,
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post("/api/runs", {
            "workspace_id": workspace_id,
            "configuration_revision": configuration_revision,
            "analyses": analyses,
            "retention_mode": retention_mode,
            "step_mode": bool(step_mode),
        }))

    def get_run(self, run_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/runs/{run_id}"))
        return dict(data.get("run") or {})

    def clone_run_workspace(self, run_id: str, *, title: str = "") -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/runs/{run_id}/clone-workspace", {"title": title},
        ))
        return dict(data.get("workspace") or {})

    def list_jobs(
        self,
        *,
        workspace_id: str = "",
        run_id: str = "",
        status: str = "",
        kind: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = {
            key: value for key, value in {
                "workspace_id": workspace_id,
                "run_id": run_id,
                "status": status,
                "kind": kind,
                "limit": limit,
            }.items() if value
        }
        data = self._expect_success(self.session.get("/api/jobs", query=query or None))
        return list(data.get("jobs") or [])

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/jobs/{job_id}"))

    def job_result(self, job_id: str) -> dict[str, Any]:
        return self.session.get(f"/api/jobs/{job_id}/result")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/cancel", {}))

    def retry_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/retry", {}))

    def approve_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/approve", {}))

    def pin_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/pin", {}))

    def unpin_job(self) -> dict[str, Any]:
        return self._expect_success(self.session.delete("/api/jobs/pin"))

    def continue_job(self, job_id: str, *, action: str = "continue", until: str = "") -> dict[str, Any]:
        payload = {"action": action}
        if until:
            payload["until"] = until
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/continue", payload))

    def job_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/jobs/{job_id}/artifacts/{name}"))

    def delete_job_artifacts(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.delete(f"/api/jobs/{job_id}/artifacts"))

    def delete_user_artifacts(self, *, workspace_id: str = "") -> dict[str, Any]:
        query = {"workspace_id": workspace_id} if workspace_id else None
        return self._expect_success(self.session.delete("/api/jobs/artifacts", query=query))

    def delete_terminal_job_history(self, *, workspace_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.delete("/api/jobs", query={"workspace_id": workspace_id})
        )

    def job_storage(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/api/jobs/storage"))

    def stream_job_id(self, job_id: str, *, after: int = 0):
        query = {"after": after} if after else None
        yield from self.session.stream_get(f"/api/jobs/{job_id}/stream", query=query)

    def list_modules(self, parent: str | None = None) -> list[dict[str, Any]]:
        if parent is None:
            return self.home_modules()
        if parent == "products":
            return [
                {"key": "products/info", "label": "产品后端信息", "kind": "module", "has_children": False},
                {"key": "products/product-groups", "label": "产品组库", "kind": "module", "has_children": False},
            ]
        if parent == "custom_factors":
            return [
                {"key": "custom_factors/factor-library", "label": "因子库", "kind": "module", "has_children": False},
                {"key": "custom_factors/workspace", "label": "本地 factor workspace", "kind": "module", "has_children": False},
                {"key": "custom_factors/operators", "label": "FactorExpr 算子", "kind": "module", "has_children": False},
            ]
        query = {"parent": parent} if parent else None
        data = self._expect_success(self.session.get("/api/testers/modules", query=query))
        if parent and data.get("parent") != parent:
            raise RuntimeError(
                "服务端 /api/testers/modules 还不是分层导航版本，"
                "请更新并重启服务端后再访问下一层。"
            )
        modules = data.get("modules")
        if not isinstance(modules, list):
            raise ValueError("服务器 modules 响应格式错误")
        return modules

    def home_modules(self) -> list[dict[str, Any]]:
        data = self.session.get("/static/config/modules.json")
        modules = data.get("modules")
        if not isinstance(modules, list):
            raise ValueError("服务器 home modules 响应格式错误")
        return [
            {
                "key": str(module.get("id") or ""),
                "label": module.get("title") or module.get("id"),
                "kind": "module",
                "path": module.get("path"),
                "description": module.get("desc"),
                "has_children": True,
            }
            for module in modules
            if module.get("id")
        ]

    def manifest(self, application: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/backtest/settings/{application}"))

    def tab_manifest(self, application: str, tab_key: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/backtest/settings/{application}/tabs/{tab_key}"))

    def list_candidates(self, kind: str, **params: Any) -> list[dict[str, Any]]:
        if kind in {"product_path_selection", "product_path_candidates", "product_path_selections"}:
            data = self._expect_success(self.session.get("/api/product-groups", query=params))
            for key in ("product_groups", "items", "selections", "groups"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            data = self._expect_success(self.session.get("/api/factor-library-overview", query=params))
            for key in ("factors", "items", "configs", "families"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return []
        raise ValueError(f"CLI 暂不支持候选列表类型: {kind}")

    def add_candidate(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind in {"factor", "factor_candidates", "factor_selections"}:
            return self._expect_success(self.session.post("/add_factor_by_params", payload))
        raise ValueError(f"CLI 暂不支持新增候选类型: {kind}")

    def create_custom_factor(
        self,
        *,
        source_code: str,
        chinese_name: str = "",
        description: str = "",
        category: str = "自编",
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/custom-factors/api/create",
                {
                    "source_code": source_code,
                    "chinese_name": chinese_name,
                    "description": description,
                    "category": category,
                },
            )
        )

    def factor_expr_operators(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/custom-factors/api/visual-operators"))

    def custom_factor_catalog(self, *, include_subordinates: bool = False) -> dict[str, Any]:
        query = {"include_subordinates": "1"} if include_subordinates else None
        return self._expect_success(self.session.get("/custom-factors/api/list", query=query))

    def validate_factor_expr(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/custom-factors/api/validate", payload))

    def create_product_group(self, *, name: str, paths: list[str]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/api/product-groups", {"name": name, "paths": paths}))

    def product_fields(self, name: str) -> dict[str, Any]:
        return self._expect_success(self.session.get("/api/product_fields", query={"name": name}))

    def factor_library_overview(
        self,
        *,
        factor_family: str = "",
        product_group: str = "",
        include_subordinates: bool = False,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if factor_family:
            query["factor_family_alias"] = factor_family
        if product_group:
            query["product_group"] = product_group
        if include_subordinates:
            query["include_subordinates"] = "1"
        return self._expect_success(self.session.get("/custom-factors/api/factor-library-overview", query=query or None))

    def factor_library_configs(self, factor_family: str, *, product_group: str = "") -> dict[str, Any]:
        query = {"product_group": product_group} if product_group else None
        return self._expect_success(self.session.get(f"/custom-factors/api/factor-library-configs/{factor_family}", query=query))

    def save_factor_library_config(
        self,
        factor_family: str,
        *,
        product_group: str,
        params_list: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"product_group": product_group, "params_list": params_list}
        if metadata:
            payload["metadata"] = metadata
        return self._expect_success(
            self.session.put(
                f"/custom-factors/api/factor-library-configs/{factor_family}",
                payload,
            )
        )

    def list_factor_research_runs(self, **params: Any) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value not in (None, "", [], ())}
        return self._expect_success(
            self.session.get("/custom-factors/api/factor-library-research-runs", query=query or None)
        )

    def save_factor_research_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/custom-factors/api/factor-library-research-runs", payload))

    def factor_research_metrics(self, **params: Any) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value not in (None, "", [], {})}
        return self._expect_success(
            self.session.get("/custom-factors/api/factor-library-research-metrics", query=query or None)
        )

    def factor_research_stability(self, **params: Any) -> dict[str, Any]:
        query = {key: value for key, value in params.items() if value not in (None, "", [], {})}
        return self._expect_success(
            self.session.get("/custom-factors/api/factor-library-research-stability", query=query or None)
        )

    def group_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_snapshot", payload))

    def group_order_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_order_flow", payload))

    def group_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_detail", payload))

    def group_ranking_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_ranking_detail", payload))

    def factor_workspace_source_root(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/custom-factors/api/source-root"))

    def save_factor_workspace_source_root(self, source_root: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/custom-factors/api/source-root", {"source_root": source_root})
        )

    def build_factor_workspace(self) -> dict[str, Any]:
        return self._expect_success(self.session.post("/custom-factors/api/workspace/build", {}))

    def sync_factor_workspace(self, *, branch_mode: str = "force") -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/custom-factors/api/workspace/sync", {"branch_mode": branch_mode})
        )

    def push_factor_workspace(self, *, branch_mode: str = "auto") -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/custom-factors/api/workspace/push", {"branch_mode": branch_mode})
        )

    def factor_workspace_git_settings(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/custom-factors/api/workspace/git-settings"))

    def save_factor_workspace_git_settings(
        self,
        *,
        git_enabled: bool,
        git_repo_root: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                "/custom-factors/api/workspace/git-settings",
                {"git_enabled": git_enabled, "git_repo_root": git_repo_root},
            )
        )

    def factor_workspace_git_action(self, action: str, **payload: Any) -> dict[str, Any]:
        data = {"action": action, **payload}
        return self._expect_success(self.session.post("/custom-factors/api/workspace/git", data))

    def _expect_success(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("success") is False:
            raise RuntimeError(str(data.get("error") or data))
        return data
