"""Authenticated HTTP client for the independent Manager control plane."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
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

    def instances(self) -> dict[str, Any]:
        return self._request("GET", "/api/worktrees")

    def action(self, instance_id: str, action: str) -> dict[str, Any]:
        routes = {
            "start": "/start",
            "stop": "/stop",
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
        authenticated: bool = True,
    ) -> dict[str, Any]:
        url = urljoin(f"{self.config.base_url}/", path.lstrip("/"))
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
                    "Manager 尚未登录，请先运行 factortester manager login"
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
