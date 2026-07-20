"""Workspace, research run, and job HTTP client methods."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchClientMixin(ClientMixinBase):
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
        data = self._expect_success(
            self.session.get(f"/api/workspaces/{workspace_id}")
        )
        return dict(data.get("workspace") or {})

    def get_workspace_configuration(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/workspaces/{workspace_id}/configuration"
        ))
        return dict(data.get("configuration") or {})

    def validate_external_factor_artifact(
        self,
        manifest_path: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/external-factor-artifacts/validate",
            {"manifest_path": manifest_path},
        ))
        return dict(data.get("artifact") or {})

    def save_configuration_template(
        self,
        workspace_id: str,
        *,
        name: str,
    ) -> dict[str, Any]:
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
            {
                "expected_revision": expected_revision,
                "configuration_id": configuration_id,
            },
        ))
        return dict(data.get("configuration") or {})

    def list_configuration_templates(self) -> list[dict[str, Any]]:
        data = self._expect_success(
            self.session.get("/api/configuration-templates")
        )
        return list(data.get("templates") or [])

    def submit_run(
        self,
        workspace_id: str,
        configuration_revision: int,
        *,
        analyses: list[str],
        retention_mode: str = "summary",
        step_mode: bool = False,
        trial_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "configuration_revision": configuration_revision,
            "analyses": analyses,
            "retention_mode": retention_mode,
            "step_mode": bool(step_mode),
        }
        if trial_binding is not None:
            payload["trial_binding"] = trial_binding
        return self._expect_success(self.session.post("/api/runs", payload))

    def preview_run(
        self,
        workspace_id: str,
        configuration_revision: int,
        *,
        analyses: list[str],
        retention_mode: str = "summary",
        step_mode: bool = False,
    ) -> dict[str, Any]:
        """Derive the exact frozen RunSpec identity without creating a run."""
        payload = {
            "workspace_id": workspace_id,
            "configuration_revision": configuration_revision,
            "analyses": analyses,
            "retention_mode": retention_mode,
            "step_mode": bool(step_mode),
        }
        return self._expect_success(
            self.session.post("/api/runs/preview", payload)
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(f"/api/runs/{run_id}"))
        return dict(data.get("run") or {})

    def clone_run_workspace(
        self,
        run_id: str,
        *,
        title: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/runs/{run_id}/clone-workspace",
            {"title": title},
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
        data = self._expect_success(
            self.session.get("/api/jobs", query=query or None)
        )
        return list(data.get("jobs") or [])

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.get(f"/api/jobs/{job_id}")
        )

    def job_result(self, job_id: str) -> dict[str, Any]:
        return self.session.get(f"/api/jobs/{job_id}/result")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/cancel", {})
        )

    def retry_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/retry", {})
        )

    def approve_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/approve", {})
        )

    def pin_job(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/pin", {})
        )

    def unpin_job(self) -> dict[str, Any]:
        return self._expect_success(self.session.delete("/api/jobs/pin"))

    def continue_job(
        self,
        job_id: str,
        *,
        action: str = "continue",
        until: str = "",
    ) -> dict[str, Any]:
        payload = {"action": action}
        if until:
            payload["until"] = until
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/continue", payload)
        )

    def job_artifact(self, job_id: str, name: str) -> dict[str, Any]:
        return self._expect_success(self.session.get(
            f"/api/jobs/{job_id}/artifacts/{name}"
        ))

    def delete_job_artifacts(self, job_id: str) -> dict[str, Any]:
        return self._expect_success(
            self.session.delete(f"/api/jobs/{job_id}/artifacts")
        )

    def delete_user_artifacts(
        self,
        *,
        workspace_id: str = "",
    ) -> dict[str, Any]:
        query = {"workspace_id": workspace_id} if workspace_id else None
        return self._expect_success(
            self.session.delete("/api/jobs/artifacts", query=query)
        )

    def delete_terminal_job_history(
        self,
        *,
        workspace_id: str,
    ) -> dict[str, Any]:
        return self._expect_success(
            self.session.delete(
                "/api/jobs",
                query={"workspace_id": workspace_id},
            )
        )

    def job_storage(self) -> dict[str, Any]:
        return self._expect_success(self.session.get("/api/jobs/storage"))

    def stream_job_id(self, job_id: str, *, after: int = 0):
        query = {"after": after} if after else None
        yield from self.session.stream_get(
            f"/api/jobs/{job_id}/stream",
            query=query,
        )
