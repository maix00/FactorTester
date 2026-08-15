"""Authenticated HTTP client for the independent Manager control plane."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from tools.cli.http import HttpClientError
from tools.cli.manager.config import ManagerConfig


class ManagerClient:
    def __init__(
        self,
        config: ManagerConfig,
        *,
        token: str = "",
        timeout: float = 30,
    ) -> None:
        self.config = config
        self.token = str(token or "").strip()
        self.timeout = timeout

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/login",
            payload={"username": username, "password": password},
            authenticated=False,
        )

    def logout(self) -> dict[str, Any]:
        return self._request("POST", "/auth/logout")

    def session(self) -> dict[str, Any]:
        return self._request("GET", "/api/session")

    def require_manager(self) -> dict[str, Any]:
        """Return the session only when the principal has Manager authority."""
        value = self.session()
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, dict) or not capabilities.get("manager"):
            raise PermissionError(
                "当前账号没有 Manager 管理权限（需要 super_admin）"
            )
        return value

    def identity(self) -> dict[str, Any]:
        """Read server-owned identity and management access metadata."""
        return self._manager_contract_request("GET", "/api/manager/identity")

    def health(self) -> dict[str, Any]:
        """Read the safe Manager, data-plane, database, and federation checks."""
        return self._manager_contract_request("GET", "/api/manager/health")

    def _manager_contract_request(
        self,
        method: str,
        path: str,
    ) -> dict[str, Any]:
        """Give an actionable error when a target is on the old Manager API."""
        try:
            return self._request(method, path)
        except HttpClientError as exc:
            if exc.status == 404:
                raise RuntimeError(
                    "目标 Manager 未提供服务器访问契约；请先发布包含 "
                    "Manager server identity/access API 的版本"
                ) from None
            raise

    def federation_servers(self) -> dict[str, Any]:
        return self._request("GET", "/api/federation/servers")

    def federation_config(self) -> dict[str, Any]:
        return self._request("GET", "/api/federation/config")

    def transfer_metrics(
        self,
        *,
        window_seconds: int = 24 * 60 * 60,
        object_kind: str = "",
        operation: str = "",
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"window_seconds": window_seconds}
        if object_kind:
            query["object_kind"] = object_kind
        if operation:
            query["operation"] = operation
        return self._request("GET", "/api/transfers/metrics", query=query)

    def control_database_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/control-database/config")

    def network_info(self) -> dict[str, Any]:
        return self._request("GET", "/api/server/network-info")

    def devices(self) -> dict[str, Any]:
        return self._request("GET", "/api/devices")

    def device_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/device/summary")

    def revoke_device(self, device_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/devices/revoke",
            payload={"device_id": str(device_id or "").strip()},
        )

    def download_access_script_to_path(
        self,
        method_id: str,
        destination: str | Path,
        *,
        expected_sha256: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Download a declared script without executing or exposing secrets."""
        target = Path(destination).expanduser()
        if target.exists() and not force:
            raise FileExistsError(
                f"refusing to overwrite existing connection script: {target}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        url = urljoin(
            f"{self.config.base_url}/",
            "api/manager/access/"
            f"{quote(str(method_id), safe='')}/script",
        )
        request = Request(
            url,
            headers={
                "Accept": "text/x-shellscript, text/plain, application/octet-stream",
                "Authorization": f"Bearer {self.token}",
            },
            method="GET",
        )
        expected = str(expected_sha256 or "").strip().lower()
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ValueError("declared connection script digest is invalid")
        temporary_name = ""
        installed = False
        hasher = hashlib.sha256()
        size = 0
        try:
            with urlopen(request, timeout=self.timeout) as response:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".download",
                    dir=str(target.parent),
                )
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        while chunk := response.read(64 * 1024):
                            size += len(chunk)
                            if size > 4 * 1024 * 1024:
                                raise ValueError("connection script is too large")
                            hasher.update(chunk)
                            stream.write(chunk)
                except BaseException:
                    Path(temporary_name).unlink(missing_ok=True)
                    temporary_name = ""
                    raise
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise HttpClientError(exc.code, url, raw) from exc
        try:
            digest = hasher.hexdigest()
            if digest != expected:
                raise ValueError("downloaded connection script digest mismatch")
            os.chmod(temporary_name, 0o700)
            os.replace(temporary_name, target)
            installed = True
        finally:
            if temporary_name and not installed:
                Path(temporary_name).unlink(missing_ok=True)
        return {
            "method_id": str(method_id),
            "path": str(target),
            "size_bytes": size,
            "sha256": digest,
            "executed": False,
        }

    def sync_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Write one authenticated, source-free Profile projection."""
        return self._request(
            "POST",
            "/api/client/profiles/sync",
            payload={"profile": profile},
        )

    def instances(self) -> dict[str, Any]:
        return self._request("GET", "/api/worktrees")

    def jobs(
        self,
        *,
        scope: str = "server",
        limit: int = 20,
        cursor: str = "",
        page: int = 1,
        source_scope: str = "",
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "scope": scope,
            "limit": limit,
            "page": page,
        }
        if cursor:
            query["cursor"] = cursor
        if source_scope:
            query["source_scope"] = source_scope
        return self._request("GET", "/api/jobs", query=query)

    def job(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/jobs/{quote(str(job_id), safe='')}"
        )

    def job_action(self, job_id: str, action: str) -> dict[str, Any]:
        if action not in {"cancel", "retry", "continue", "approve"}:
            raise ValueError("unsupported Job action")
        return self._request(
            "POST",
            f"/api/jobs/{quote(str(job_id), safe='')}/{action}",
            payload={},
        )

    def job_ports(self) -> dict[str, Any]:
        return self._request("GET", "/api/jobs/ports")

    def job_artifacts(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/jobs/{quote(str(job_id), safe='')}/artifacts"
        )

    def delete_job_artifacts(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE", f"/api/jobs/{quote(str(job_id), safe='')}/artifacts"
        )

    def job_storage(self) -> dict[str, Any]:
        return self._request("GET", "/api/jobs/storage")

    def artifact_download_to_path(
        self,
        job_id: str,
        name: str,
        destination: str | Path,
    ) -> dict[str, Any]:
        """Issue a short-lived access capability, then stream through 7997."""
        issued = self._request(
            "POST",
            f"/api/jobs/{quote(str(job_id), safe='')}/artifacts/"
            f"{quote(str(name), safe='')}/access",
            payload={},
        )
        access = issued.get("access")
        artifact = issued.get("artifact")
        if not isinstance(access, dict) or not isinstance(artifact, dict):
            raise ValueError("artifact transfer authorization is incomplete")
        from tools.cli.capability_download import download_capability_to_path

        return {
            "job_id": str(job_id),
            "name": str(name),
            **download_capability_to_path(
                access,
                destination,
                timeout=self.timeout,
                expected_sha256=str(artifact.get("content_hash") or ""),
                content_type=str(
                    artifact.get("content_type") or "application/octet-stream"
                ),
            ),
        }

    def research_graph_versions(self, graph_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/research-graphs/{quote(str(graph_id), safe='')}/versions",
        )

    def active_research_graph(self, graph_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/research-graphs/{quote(str(graph_id), safe='')}/active",
        )

    def activate_research_graph(
        self,
        graph_id: str,
        version: int,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/research-graphs/{quote(str(graph_id), safe='')}/versions/"
            f"{int(version)}/activate",
            payload={},
        )

    def action(self, instance_id: str, action: str) -> dict[str, Any]:
        routes = {
            "start": "/start",
            "stop": "/stop",
            "restart-api": "/restart-api",
            "restart-bundle": "/restart-bundle",
            "restart-web": "/restart-api",
            "restart-all": "/restart-bundle",
            "force-stop": "/force-stop",
        }
        route = routes.get(action)
        if route is None:
            raise ValueError("unsupported Manager action")
        return self._request(
            "POST",
            route,
            form={"instance_id": str(instance_id or "").strip()},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        url = urljoin(f"{self.config.base_url}/", path.lstrip("/"))
        if query:
            encoded = urlencode([
                (key, value) for key, value in query.items()
                if value is not None and value != ""
            ])
            if encoded:
                url = f"{url}?{encoded}"
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if authenticated:
            if not self.token:
                raise RuntimeError(
                    "Manager 尚未登录，请先运行 factortester-manager login"
                )
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise HttpClientError(exc.code, url, raw) from exc
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Manager returned invalid JSON")
        return value
