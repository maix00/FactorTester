"""Authenticated HTTP gateway for private Manager federation."""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

from server.manager.domain.federation_transport import FederationTransport
from server.manager.http.gateway import GatewayResponse

from .models import ServiceRoute

MAX_ENVELOPE_BYTES = 16 * 1024 * 1024

class FederatedGateway:
    """Forward one request through a registered Manager proxy."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        transport: FederationTransport | None = None,
    ) -> None:
        self.timeout = max(1.0, float(timeout))
        self.transport = transport or FederationTransport()

    @staticmethod
    def _peer_url(route: ServiceRoute, path: str) -> str:
        endpoint = str(route.peer_control_endpoint or "").strip().rstrip("/")
        if endpoint.lower() in {"", "none", "null"}:
            raise ConnectionError("peer control endpoint is unavailable")
        return endpoint + path

    def request(
        self,
        route: ServiceRoute,
        *,
        path: str,
        principal: str,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str = "application/json",
        origin_server_id: str = "",
    ) -> GatewayResponse:
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = {
            "server_id": route.server_id,
            "port": route.port,
            "path": path,
            "principal": principal,
            "method": method,
            "content_type": content_type,
            "body_b64": base64.b64encode(body or b"").decode("ascii"),
        }
        if str(origin_server_id or "").strip():
            payload["origin_server_id"] = str(origin_server_id).strip()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/proxy"),
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                response_body = response.read(MAX_ENVELOPE_BYTES)
                status = response.status
                content_type_header = response.headers.get_content_type()
        except HTTPError as exc:
            response_body = exc.read(MAX_ENVELOPE_BYTES)
            status = exc.code
            content_type_header = exc.headers.get_content_type()
        except (URLError, OSError) as exc:
            raise ConnectionError("federated service is unavailable") from exc
        try:
            envelope = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated service returned invalid response") from exc
        if not isinstance(envelope, dict):
            raise ConnectionError("federated service returned invalid response")
        encoded = str(envelope.get("body_b64") or "")
        try:
            result_body = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            raise ConnectionError("federated service returned invalid body") from exc
        return GatewayResponse(
            status=int(envelope.get("status") or status),
            body=result_body,
            content_type=str(envelope.get("content_type") or content_type_header),
            content_disposition=str(envelope.get("content_disposition") or ""),
            etag=str(envelope.get("etag") or ""),
        )

    def json(
        self,
        route: ServiceRoute,
        *,
        path: str,
        principal: str,
    ) -> dict[str, object]:
        response = self.request(route, path=path, principal=principal)
        if not 200 <= response.status < 300:
            raise ConnectionError(f"federated service returned HTTP {response.status}")
        return response.json_object()

    def query_jobs(
        self,
        route: ServiceRoute,
        *,
        requester_server_id: str,
        principal: str,
        scope: str,
        page: int = 1,
        limit: int = 100,
        username: str = "",
        object_kind: str = "",
        object_ref: str = "",
        object_owner_ref: str = "",
        object_alias: str = "",
    ) -> dict[str, object]:
        """Query one peer's local job projection through WireGuard 17998.

        This is deliberately separate from ``/api/federation/proxy``: the
        peer must call its own local service projection with federation
        disabled, otherwise two Managers could recursively fan out to one
        another.  The endpoint returns summaries only; details and artifacts
        still use the selected job's normal 7998/7997 route.
        """
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = {
            "requester_server_id": str(requester_server_id),
            "principal": str(principal),
            "scope": str(scope),
            "page": max(1, int(page)),
            "limit": max(1, min(100, int(limit))),
        }
        if username:
            payload["username"] = str(username)
        for key, value in (
            ("object_kind", object_kind),
            ("object_ref", object_ref),
            ("object_owner_ref", object_owner_ref),
            ("object_alias", object_alias),
        ):
            if str(value or "").strip():
                payload[key] = str(value).strip()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/jobs/query"),
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                response_body = response.read(MAX_ENVELOPE_BYTES)
                status = response.status
        except HTTPError as exc:
            response_body = exc.read(MAX_ENVELOPE_BYTES)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated job query is unavailable") from exc
        try:
            value = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated job query response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated job query response is invalid")
        if not 200 <= status < 300 or value.get("success") is False:
            raise ConnectionError(
                str(value.get("error") or f"federated job query returned HTTP {status}")
            )
        return value

    def public_data(
        self,
        route: ServiceRoute,
        *,
        kind: str,
        operation: str,
        principal: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Read one bounded safe projection from a peer Manager.

        This control-plane request is deliberately separate from the generic
        service proxy.  The peer endpoint owns the allow-list for research,
        Profile, and factor metadata operations and never accepts source-code
        or device-local path requests.
        """
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        request_payload = {
            "kind": str(kind or "").strip(),
            "operation": str(operation or "").strip(),
            "principal": str(principal or "").strip(),
            "payload": dict(payload or {}),
        }
        if not request_payload["kind"] or not request_payload["operation"]:
            raise ValueError("federated public-data request is incomplete")
        raw = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/public-data"),
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                response_body = response.read(MAX_ENVELOPE_BYTES)
                status = response.status
        except HTTPError as exc:
            response_body = exc.read(MAX_ENVELOPE_BYTES)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated public data is unavailable") from exc
        try:
            value = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated public data response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated public data response is invalid")
        if not 200 <= status < 300 or value.get("success") is False:
            raise ConnectionError(
                str(value.get("error") or f"federated public data returned HTTP {status}")
            )
        return value

    def capabilities(
        self,
        route: ServiceRoute,
        *,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Read a peer Manager's local data-source capability projection.

        This is a control-plane request.  It intentionally does not go
        through a peer's service port, so a data-source catalog remains
        available even when the peer's selected execution port is stopped.
        """
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        request_payload = dict(payload or {})
        # A host may advertise more than one execution service.  Keep the
        # target identity in the control-plane request so a peer can report
        # which branch/port its snapshot belongs to instead of returning an
        # ambiguous host-wide answer.
        request_payload.setdefault("server_id", route.server_id)
        request_payload.setdefault("port", route.port)
        request_payload.setdefault("branch", route.branch)
        raw = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/capabilities"),
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                response_body = response.read(4 * 1024 * 1024)
                status = response.status
        except HTTPError as exc:
            response_body = exc.read(4 * 1024 * 1024)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated capability service is unavailable") from exc
        try:
            value = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated capability response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated capability response is invalid")
        if not 200 <= status < 300:
            raise ConnectionError(
                str(value.get("error") or f"federated capability returned HTTP {status}")
            )
        return value

    def sync_events(
        self,
        route: ServiceRoute,
        *,
        requester_server_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        """Pull this peer's relevant control events through WireGuard 17998."""
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = json.dumps({
            "requester_server_id": str(requester_server_id),
            "after_sequence": max(0, int(after_sequence)),
            "limit": max(1, min(int(limit), 200)),
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/sync/events"),
            data=payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024)
                status = response.status
        except HTTPError as exc:
            raw = exc.read(8 * 1024 * 1024)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated control sync is unavailable") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated control sync response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated control sync response is invalid")
        if not 200 <= status < 300:
            raise ConnectionError(
                str(value.get("error") or f"federated control sync returned HTTP {status}")
            )
        return value

    def reconcile_jobs(
        self,
        route: ServiceRoute,
        *,
        requester_server_id: str,
        job_ids: list[str] | tuple[str, ...] = (),
        limit: int = 200,
    ) -> dict[str, object]:
        """Request a bounded current projection after a cursor repair."""
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = json.dumps({
            "requester_server_id": str(requester_server_id),
            "job_ids": [str(item) for item in job_ids[:200]],
            "limit": max(1, min(int(limit), 200)),
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/sync/reconcile"),
            data=payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.transport.open(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024)
                status = response.status
        except HTTPError as exc:
            raw = exc.read(8 * 1024 * 1024)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated control reconcile is unavailable") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated control reconcile response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated control reconcile response is invalid")
        if not 200 <= status < 300:
            raise ConnectionError(
                str(value.get("error") or f"federated control reconcile returned HTTP {status}")
            )
        return value

    def open_stream(
        self,
        route: ServiceRoute,
        *,
        path: str,
        principal: str,
        last_event_id: str = "",
    ):
        """Open a service event stream through peer control port 17998."""
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = {
            "server_id": route.server_id,
            "port": route.port,
            "path": path,
            "principal": principal,
            "last_event_id": last_event_id,
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/stream"),
            data=raw,
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {route.proxy_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return self.transport.open(request, timeout=self.timeout)
        except HTTPError:
            raise
        except (URLError, OSError) as exc:
            raise ConnectionError("federated service is unavailable") from exc
