"""Outbound client for the FactorTester WireGuard peer-control API."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request

from server.manager.domain.federation_transport import FederationTransport
from server.manager.transfers.node_keys import NodeKey


class NodeControlClient:
    def __init__(
        self,
        endpoint: str,
        *,
        key: NodeKey,
        enrollment_token: str = "",
        transport: FederationTransport | None = None,
    ) -> None:
        self.endpoint = str(endpoint or "").strip().rstrip("/")
        if not self.endpoint:
            raise ValueError("peer control endpoint is required")
        self.key = key
        self.enrollment_token = str(enrollment_token or "").strip()
        self.transport = transport or FederationTransport()

    def enroll(self) -> dict[str, object]:
        if not self.enrollment_token:
            raise PermissionError("node enrollment token is required")
        return self._json_request(
            "/api/federation/node/enroll",
            method="POST",
            payload=self.key.public_record(),
            headers={"Authorization": f"Bearer {self.enrollment_token}"},
        )

    def signed_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        timeout: float = 10.0,
    ) -> dict[str, object]:
        body = _json_bytes(payload)
        challenge = self._challenge()
        return self._json_request(
            path,
            method="POST",
            body=body,
            headers=self._signature_headers(
                challenge=challenge,
                method="POST",
                path=path,
                body=body,
            ),
            timeout=timeout,
        )

    def _challenge(self) -> str:
        path = "/api/federation/node/challenge?" + urlencode({
            "node_id": self.key.node_id,
        })
        value = self._json_request(path, method="GET")
        challenge = str(value.get("challenge") or "").strip()
        if not challenge:
            raise PermissionError("node challenge is unavailable")
        return challenge

    def _signature_headers(
        self,
        *,
        challenge: str,
        method: str,
        path: str,
        body: bytes,
    ) -> dict[str, str]:
        return {
            "X-FactorTester-Node-ID": self.key.node_id,
            "X-FactorTester-Node-Challenge": challenge,
            "X-FactorTester-Node-Signature": self.key.sign_request(
                challenge=challenge,
                method=method,
                path=path,
                body=body,
            ),
        }

    def _json_request(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, object] | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, object]:
        raw = body if body is not None else (
            _json_bytes(payload) if payload is not None else None
        )
        request = Request(
            self.endpoint + path,
            data=raw,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if raw else {}),
                **(headers or {}),
            },
            method=method,
        )
        with self.transport.open(request, timeout=timeout) as response:
            value = json.loads(response.read(1024 * 1024).decode("utf-8"))
        if not isinstance(value, dict) or value.get("success") is False:
            raise ValueError("peer control response is invalid")
        return value


def _json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
