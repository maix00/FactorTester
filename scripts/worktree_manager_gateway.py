"""Authenticated byte-for-byte gateway to FactorTester service ports.

The Manager is the only client-visible endpoint.  Service ports remain an
internal execution detail and keep their existing API paths unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class GatewayResponse:
    status: int
    body: bytes
    content_type: str
    content_disposition: str = ""
    etag: str = ""

    def json_object(self) -> dict[str, object]:
        value = json.loads(self.body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("service returned an invalid response")
        return value


class ServiceGateway:
    """Forward an authenticated user request to an approved service port."""

    def __init__(
        self,
        *,
        available_ports: Callable[[], list[int]],
        capability_token: Callable[[], str],
        timeout: float = 12.0,
    ) -> None:
        self._available_ports = available_ports
        self._capability_token = capability_token
        self.timeout = timeout

    def request(
        self,
        *,
        port: int,
        path: str,
        principal: str,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> GatewayResponse:
        if port not in self._available_ports():
            raise ValueError("service port is unavailable")
        headers = {
            "Accept": "*/*",
            "X-FactorTester-Principal": principal,
            "X-FactorTester-Manager": self._capability_token(),
        }
        if body is not None:
            headers["Content-Type"] = content_type
        request = Request(
            f"http://127.0.0.1:{port}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return GatewayResponse(
                    status=response.status,
                    body=response.read(),
                    content_type=response.headers.get_content_type(),
                    content_disposition=str(
                        response.headers.get("Content-Disposition") or ""
                    ),
                    etag=str(response.headers.get("ETag") or ""),
                )
        except HTTPError as exc:
            return GatewayResponse(
                status=exc.code,
                body=exc.read(),
                content_type=exc.headers.get_content_type(),
                content_disposition=str(
                    exc.headers.get("Content-Disposition") or ""
                ),
                etag=str(exc.headers.get("ETag") or ""),
            )
        except URLError as exc:
            raise ConnectionError("service port is unavailable") from exc

    def json(
        self, *, port: int, path: str, principal: str,
    ) -> dict[str, object]:
        response = self.request(port=port, path=path, principal=principal)
        if not 200 <= response.status < 300:
            raise ConnectionError(
                f"service returned HTTP {response.status}"
            )
        return response.json_object()
