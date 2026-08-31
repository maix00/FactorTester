"""Job lifecycle and artifact HTTP client methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from .client_base import ClientMixinBase
from .http import DEFAULT_BINARY_LIMIT, BinaryResponse


class JobsClientMixin(ClientMixinBase):
    def list_job_ports(self) -> list[int]:
        data = self._expect_success(self.session.get("/api/jobs/ports"))
        return [
            int(value) for value in data.get("ports") or []
            if isinstance(value, int) and 1 <= value <= 65535
        ]

    def list_jobs(
        self,
        *,
        workspace_id: str = "",
        run_id: str = "",
        status: str = "",
        kind: str = "",
        limit: int = 20,
        all_ports: bool = True,
    ) -> list[dict[str, Any]]:
        query = {
            key: value for key, value in {
                "workspace_id": workspace_id,
                "run_id": run_id,
                "status": status,
                "kind": kind,
                "limit": limit,
                "port": "all" if all_ports else "",
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

    def retry_job(
        self,
        job_id: str,
        *,
        performance_profile: dict[str, Any] | None = None,
        margin_execution_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {}
        if performance_profile is not None:
            payload["performance_profile"] = dict(performance_profile)
        if margin_execution_profile is not None:
            payload["margin_execution_profile"] = dict(margin_execution_profile)
        return self._expect_success(
            self.session.post(f"/api/jobs/{job_id}/retry", payload)
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

    def job_artifact(
        self,
        job_id: str,
        name: str,
        *,
        maximum_bytes: int = DEFAULT_BINARY_LIMIT,
    ) -> BinaryResponse:
        issued, access, artifact = self._job_artifact_access(job_id, name)
        del issued
        return self.session.capability_download(
            access,
            maximum_bytes=maximum_bytes,
            expected_sha256=str(artifact.get("content_hash") or ""),
            content_type=str(
                artifact.get("content_type") or "application/octet-stream"
            ),
        )

    def job_artifact_to_path(
        self,
        job_id: str,
        name: str,
        destination: str | Path,
    ) -> dict[str, Any]:
        _issued, access, artifact = self._job_artifact_access(job_id, name)
        return {
            "job_id": str(job_id),
            "name": str(name),
            **self.session.capability_download_to_path(
                access,
                destination,
                expected_sha256=str(artifact.get("content_hash") or ""),
                content_type=str(
                    artifact.get("content_type") or "application/octet-stream"
                ),
            ),
        }

    def _job_artifact_access(
        self,
        job_id: str,
        name: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        issued = self._expect_success(self.session.post(
            f"/api/jobs/{quote(str(job_id), safe='')}/artifacts/"
            f"{quote(str(name), safe='')}/access",
            {},
        ))
        access = issued.get("access")
        artifact = issued.get("artifact")
        if not isinstance(access, dict) or not isinstance(artifact, dict):
            raise ValueError("artifact transfer authorization is incomplete")
        return issued, access, artifact

    def job_artifact_capabilities(self) -> list[dict[str, Any]]:
        data = self._expect_success(
            self.session.get("/api/jobs/artifact-capabilities")
        )
        return list(data.get("outputs") or [])

    def list_job_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        data = self._expect_success(
            self.session.get(f"/api/jobs/{job_id}/artifacts")
        )
        return list(data.get("artifacts") or [])

    def generate_job_artifacts(
        self,
        job_id: str,
        *,
        output_requests: list[str],
    ) -> dict[str, Any]:
        return self._expect_success(self.session.post(
            f"/api/jobs/{job_id}/supplementals",
            {
                "kind": "report_output_generation",
                "params": {"output_requests": list(output_requests)},
            },
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

