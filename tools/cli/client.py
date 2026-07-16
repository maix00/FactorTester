"""High-level FactorTester HTTP API client."""

from __future__ import annotations

from typing import Any

from .http import HttpSession


class FactorTesterClient:
    def __init__(self, session: HttpSession) -> None:
        self.session = session

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._expect_success(self.session.post("/login", {"username": username, "password": password}))

    def create_workspace(
        self,
        *,
        factor_family_alias: str = "",
        title: str = "Single factor research",
        draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post("/api/workspaces", {
            "kind": "single_factor",
            "title": title,
            "factor_family_alias": factor_family_alias,
            "draft": draft or {},
        }))
        return dict(data.get("workspace") or {})

    def list_workspaces(self) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get("/api/workspaces"))
        return list(data.get("workspaces") or [])

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/workspaces/{workspace_id}"))
        return dict(data.get("workspace") or {})

    def update_workspace(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        draft: dict[str, Any],
        title: str | None = None,
        factor_family_alias: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "expected_revision": expected_revision,
            "draft": draft,
        }
        if title is not None:
            payload["title"] = title
        if factor_family_alias is not None:
            payload["factor_family_alias"] = factor_family_alias
        data = self._expect_success(
            self.session.patch(f"/api/workspaces/{workspace_id}", payload)
        )
        return dict(data.get("workspace") or {})

    def submit_run(
        self,
        workspace_id: str,
        workspace_revision: int,
        *,
        analyses: list[str],
        lifecycle_policy: str = "durable",
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post("/api/runs", {
            "workspace_id": workspace_id,
            "workspace_revision": workspace_revision,
            "analyses": analyses,
            "lifecycle_policy": lifecycle_policy,
        }))

    def get_run(self, run_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/runs/{run_id}"))
        return dict(data.get("run") or {})

    def list_jobs(
        self,
        *,
        workspace_id: str = "",
        run_id: str = "",
        status: str = "",
        kind: str = "",
    ) -> list[dict[str, Any]]:
        query = {
            key: value for key, value in {
                "workspace_id": workspace_id,
                "run_id": run_id,
                "status": status,
                "kind": kind,
            }.items() if value
        }
        data = self._expect_success(self.session.get("/api/jobs", query=query or None))
        return list(data.get("jobs") or [])

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/jobs/{job_id}"))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/cancel", {}))

    def retry_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/retry", {}))

    def continue_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(self.session.post(f"/api/jobs/{job_id}/continue", {}))

    def job_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(f"/api/jobs/{job_id}/artifacts/{name}"))

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

    def run_group_test_stream(self, payload: dict[str, Any]):
        job = self.submit_job("backtest", payload)
        yield from self.stream_job(job)

    def group_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_snapshot", payload))

    def group_order_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_order_flow", payload))

    def group_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_detail", payload))

    def group_ranking_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(self.session.post("/get_group_ranking_detail", payload))

    def run_ic_test_stream(self, payload: dict[str, Any]):
        job = self.submit_job("ic", payload)
        yield from self.stream_job(job)

    def run_factor_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.run_job_result("factor_evaluation", payload)

    def run_factor_type_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.run_job_result("factor_type_analysis", payload)

    def submit_job(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._expect_success(
            self.session.post("/api/jobs", {"kind": kind, "payload": payload})
        )

    def stream_job(self, job: dict[str, Any]):
        stream_url = str(job.get("stream_url") or "")
        if not stream_url:
            raise ValueError("服务器 job 响应缺少 stream_url")
        yield from self.session.stream_get(stream_url)

    def job_result(self, job: dict[str, Any]) -> dict[str, Any]:
        result_url = str(job.get("result_url") or "")
        if not result_url:
            job_id = str(job.get("job_id") or "")
            if not job_id:
                raise ValueError("服务器 job 响应缺少 result_url/job_id")
            result_url = f"/api/jobs/{job_id}/result"
        return self._expect_success(self.session.get(result_url))

    def run_job_result(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.submit_job(kind, payload)
        terminal_error: Any = None
        for event in self.stream_job(job):
            event_name = str(event.get("event") or "message")
            data = event.get("data")
            if event_name == "error":
                terminal_error = data
            elif event_name == "result" and isinstance(data, dict):
                return data
        if terminal_error is not None:
            message = terminal_error.get("error") if isinstance(terminal_error, dict) else terminal_error
            raise RuntimeError(str(message))
        result = self.job_result(job)
        payload_result = result.get("result")
        if isinstance(payload_result, dict):
            return payload_result
        raise ValueError("服务器 job result 响应缺少 result")

    def list_single_factor_setting_templates(self, factor_family: str) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(f"/api/single_factor_setting_templates/{factor_family}"))
        templates = data.get("templates")
        if not isinstance(templates, list):
            raise ValueError("服务器模板列表响应格式错误")
        return templates

    def get_single_factor_setting_template(self, factor_family: str, template_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/single_factor_setting_templates/{factor_family}/{template_id}"))
        template = data.get("template")
        if not isinstance(template, dict):
            raise ValueError("服务器模板详情响应格式错误")
        return template

    def save_single_factor_setting_template(
        self,
        factor_family: str,
        *,
        name: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(
                f"/api/single_factor_setting_templates/{factor_family}",
                {"name": name, "ff_alias": factor_family, "snapshot": snapshot},
            )
        )

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
