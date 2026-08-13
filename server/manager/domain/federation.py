"""Federated Manager registration and authenticated service forwarding.

The 7998 Manager is the control-plane entry point.  A Manager on another host
may register its feature worktrees and expose one authenticated proxy endpoint
for those service ports.  SQLite and job execution remain local to each host;
this module only carries routing metadata and request/response envelopes.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from server.jobs.artifact_data_plane import (
    artifact_data_endpoint,
    artifact_data_url,
)
from server.manager.domain.federation_transport import FederationTransport
from server.manager.http.gateway import GatewayResponse


REGISTRY_SCHEMA_VERSION = 1
FEDERATION_CONFIG_SCHEMA_VERSION = 1
DEFAULT_LEASE_SECONDS = 30.0
MAX_ENVELOPE_BYTES = 16 * 1024 * 1024


class FederationError(RuntimeError):
    """Base class for federation failures."""


class TargetUnavailable(FederationError):
    """A registered target is offline or cannot be reached."""


class TargetNotFound(FederationError):
    """No registered target matches the requested selector."""


@dataclass(frozen=True, slots=True)
class ServiceRoute:
    """One routable FactorTester service endpoint."""

    server_id: str
    role: str
    branch: str
    revision: str
    port: int
    features: tuple[str, ...] = ()
    endpoint: str = ""
    artifact_endpoint: str = ""
    artifact_port: int = 7997
    peer_control_endpoint: str = ""
    peer_data_endpoint: str = ""
    proxy_token: str = ""
    remote: bool = False
    online: bool = True
    load: float = 0.0
    active_jobs: int = 0
    queue_depth: int = 0
    latency_ms: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "server_id": self.server_id,
            "role": self.role,
            "branch": self.branch,
            "revision": self.revision,
            "port": self.port,
            "features": list(self.features),
            "endpoint": self.endpoint,
            "artifact_endpoint": self.artifact_endpoint,
            "artifact_port": self.artifact_port,
            "remote": self.remote,
            "online": self.online,
            "load": self.load,
            "active_jobs": self.active_jobs,
            "queue_depth": self.queue_depth,
            "latency_ms": self.latency_ms,
        }


def _string(value: object, *, field: str, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    return result


def _features(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("features must be a list")
    values = {
        str(item).strip()
        for item in value
        if str(item).strip()
    }
    return tuple(sorted(values))


def _port_descriptors(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("ports must be a list")
    result: list[dict[str, object]] = []
    seen: set[int] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each port descriptor must be an object")
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer") from exc
        if not 1 <= port <= 65535 or port in seen:
            raise ValueError("ports must be unique integers from 1 to 65535")
        seen.add(port)
        result.append({
            "port": port,
            "branch": str(item.get("branch") or "").strip(),
            "revision": str(item.get("revision") or "").strip(),
            "features": list(_features(item.get("features"))),
            "online": bool(item.get("online", True)),
            "load": _load_metrics(item.get("load")),
        })
    return result


def _load_metrics(value: object) -> dict[str, float | int]:
    if not isinstance(value, dict):
        return {
            "load": 0.0,
            "active_jobs": 0,
            "queue_depth": 0,
        }
    try:
        active_jobs = max(0, int(value.get("active_jobs") or 0))
        queue_depth = max(0, int(value.get("queue_depth") or 0))
        load = max(
            0.0,
            float(value.get("load") or (active_jobs * 2 + queue_depth)),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("load metrics must be numeric") from exc
    return {
        "load": load,
        "active_jobs": active_jobs,
        "queue_depth": queue_depth,
    }


def _port_selection(value: object) -> list[int]:
    """Normalise the local ports explicitly advertised to a peer Manager."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("ports must be a list")
    result: list[int] = []
    for item in value:
        try:
            port = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("ports must contain integers") from exc
        if not 1 <= port <= 65535:
            raise ValueError("ports must be integers from 1 to 65535")
        if port not in result:
            result.append(port)
    return sorted(result)


def _url(value: object, *, field: str, required: bool = False) -> str:
    result = str(value or "").strip().rstrip("/")
    if not result:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http or https URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not include credentials")
    return result


_FEDERATION_CONFIG_DEFAULTS: dict[str, object] = {
    "schema_version": FEDERATION_CONFIG_SCHEMA_VERSION,
    "enabled": False,
    "register_url": "",
    "public_endpoint": "",
    "artifact_endpoint": "",
    "registration_token": "",
    "ports": [],
    "interval": 10.0,
}


def _normalise_federation_config(
    payload: dict[str, object] | None = None,
    *,
    base: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        **_FEDERATION_CONFIG_DEFAULTS,
        **(base or {}),
        **(payload or {}),
    }
    try:
        interval = float(value.get("interval") or 10.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("interval must be a number") from exc
    return {
        "schema_version": FEDERATION_CONFIG_SCHEMA_VERSION,
        "enabled": bool(value.get("enabled", False)),
        "register_url": _url(value.get("register_url"), field="register_url"),
        "public_endpoint": _url(
            value.get("public_endpoint"), field="public_endpoint",
        ),
        "artifact_endpoint": _url(
            value.get("artifact_endpoint"), field="artifact_endpoint",
        ),
        "registration_token": str(value.get("registration_token") or "").strip(),
        "ports": _port_selection(value.get("ports")),
        "interval": max(3.0, min(300.0, interval)),
    }


class FederationConfigStore:
    """Owner-only persistent settings for a feature Manager attachment.

    The registration token is deliberately kept in this file instead of the
    browser or a checked-in deployment file.  ``public()`` never returns it;
    the Web settings page only receives a boolean indicating whether one is
    configured.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> dict[str, object]:
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                return _normalise_federation_config()
            if not isinstance(value, dict):
                return _normalise_federation_config()
            try:
                return _normalise_federation_config(value)
            except ValueError:
                return _normalise_federation_config()

    def merged(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("federation config must be an object")
        allowed = {
            "enabled", "register_url", "public_endpoint", "artifact_endpoint",
            "registration_token", "ports", "interval",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown federation config fields: {', '.join(unknown)}")
        return _normalise_federation_config(payload, base=self.load())

    def save(self, value: dict[str, object]) -> dict[str, object]:
        normalised = _normalise_federation_config(value)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        with self._lock:
            temporary.write_text(
                json.dumps(normalised, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        return normalised

    @staticmethod
    def public(value: dict[str, object]) -> dict[str, object]:
        normalised = _normalise_federation_config(value)
        return {
            key: item
            for key, item in normalised.items()
            if key != "registration_token"
        } | {
            "registration_token_configured": bool(
                str(normalised.get("registration_token") or "")
            ),
        }


def _normalise_registration(payload: dict[str, object]) -> dict[str, object]:
    server_id = _string(payload.get("server_id"), field="server_id")
    role = _string(payload.get("role"), field="role")
    if role not in {"main", "feat"}:
        raise ValueError("role must be main or feat")
    endpoint = _string(payload.get("endpoint"), field="endpoint").rstrip("/")
    proxy_token = _string(payload.get("proxy_token"), field="proxy_token")
    ports = _port_descriptors(payload.get("ports"))
    artifact_endpoint = _url(
        payload.get("artifact_endpoint"), field="artifact_endpoint",
    )
    try:
        artifact_port = int(payload.get("artifact_port") or 7997)
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact_port must be an integer") from exc
    if not 1 <= artifact_port <= 65535:
        raise ValueError("artifact_port must be between 1 and 65535")
    raw_latency = payload.get("latency_ms")
    if raw_latency in (None, ""):
        latency_ms: float | None = None
    else:
        try:
            latency_ms = max(0.0, float(raw_latency))
        except (TypeError, ValueError) as exc:
            raise ValueError("latency_ms must be numeric") from exc
    transfer_node = payload.get("transfer_node")
    if transfer_node is not None and not isinstance(transfer_node, dict):
        raise ValueError("transfer_node must be an object")
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "server_id": server_id,
        "role": role,
        "branch": str(payload.get("branch") or "").strip(),
        "revision": str(payload.get("revision") or "").strip(),
        "features": list(_features(payload.get("features"))),
        "endpoint": endpoint,
        "artifact_endpoint": artifact_endpoint,
        "artifact_port": artifact_port,
        "proxy_token": proxy_token,
        "ports": ports,
        "load": _load_metrics(payload.get("load")),
        "latency_ms": latency_ms,
        "last_seen": float(payload.get("last_seen") or time.time()),
        "lease_seconds": max(
            5.0,
            min(300.0, float(payload.get("lease_seconds") or DEFAULT_LEASE_SECONDS)),
        ),
        "transfer_node": dict(transfer_node or {}),
    }


class FederatedServerRegistry:
    """Small atomic JSON registry owned by the Manager control plane."""

    def __init__(
        self,
        path: str | Path,
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = max(5.0, min(300.0, float(lease_seconds)))
        self._lock = threading.RLock()
        self._servers: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            return {}
        servers = payload.get("servers")
        if not isinstance(servers, dict):
            return {}
        result: dict[str, dict[str, object]] = {}
        for server_id, value in servers.items():
            if not isinstance(value, dict):
                continue
            try:
                normalised = _normalise_registration(value)
            except (TypeError, ValueError):
                continue
            if normalised["server_id"] != str(server_id):
                continue
            result[str(server_id)] = normalised
        return result

    def _save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        payload = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "servers": self._servers,
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def register(self, payload: dict[str, object]) -> dict[str, object]:
        normalised = _normalise_registration(payload)
        normalised["last_seen"] = time.time()
        normalised["lease_seconds"] = self.lease_seconds
        with self._lock:
            self._servers[str(normalised["server_id"])] = normalised
            self._save()
        return self.describe(str(normalised["server_id"])) or normalised

    def unregister(self, server_id: str) -> bool:
        with self._lock:
            removed = self._servers.pop(str(server_id), None) is not None
            if removed:
                self._save()
            return removed

    def describe(self, server_id: str) -> dict[str, object] | None:
        with self._lock:
            value = self._servers.get(str(server_id))
            return dict(value) if value is not None else None

    @staticmethod
    def _online(value: dict[str, object], now: float) -> bool:
        try:
            last_seen = float(value.get("last_seen") or 0)
            lease = float(value.get("lease_seconds") or DEFAULT_LEASE_SECONDS)
        except (TypeError, ValueError):
            return False
        return now - last_seen <= max(5.0, lease)

    def servers(
        self,
        *,
        include_offline: bool = True,
        now: float | None = None,
    ) -> list[dict[str, object]]:
        current = time.time() if now is None else float(now)
        with self._lock:
            values = []
            for value in self._servers.values():
                item = dict(value)
                item["online"] = self._online(value, current)
                if include_offline or item["online"]:
                    values.append(item)
        return sorted(values, key=lambda item: str(item.get("server_id") or ""))

    def routes(
        self,
        *,
        include_offline: bool = False,
        now: float | None = None,
    ) -> list[ServiceRoute]:
        result: list[ServiceRoute] = []
        for server in self.servers(include_offline=include_offline, now=now):
            online = bool(server.get("online"))
            base_branch = str(server.get("branch") or "")
            base_revision = str(server.get("revision") or "")
            base_features = _features(server.get("features"))
            for descriptor in server.get("ports") or []:
                if not isinstance(descriptor, dict):
                    continue
                try:
                    port = int(descriptor.get("port") or 0)
                except (TypeError, ValueError):
                    continue
                descriptor_metrics = descriptor.get("load")
                if not isinstance(descriptor_metrics, dict):
                    descriptor_metrics = server.get("load")
                metrics = _load_metrics(descriptor_metrics)
                result.append(ServiceRoute(
                    server_id=str(server.get("server_id") or ""),
                    role=str(server.get("role") or ""),
                    branch=str(descriptor.get("branch") or base_branch),
                    revision=str(descriptor.get("revision") or base_revision),
                    port=port,
                    features=tuple(sorted({
                        *base_features,
                        *_features(descriptor.get("features")),
                    })),
                    endpoint=str(server.get("endpoint") or ""),
                    artifact_endpoint=str(
                        server.get("artifact_endpoint") or ""
                    ),
                    artifact_port=int(server.get("artifact_port") or 7997),
                    peer_control_endpoint=str(
                        (
                            (server.get("transfer_node") or {}).get(
                                "peer_control_endpoint"
                            )
                            or ""
                        )
                        if isinstance(server.get("transfer_node"), dict)
                        else ""
                    ).rstrip("/"),
                    peer_data_endpoint=str(
                        (
                            (server.get("transfer_node") or {}).get(
                                "peer_data_endpoint"
                            )
                            or ""
                        )
                        if isinstance(server.get("transfer_node"), dict)
                        else ""
                    ).rstrip("/"),
                    proxy_token=str(server.get("proxy_token") or ""),
                    remote=True,
                    online=online and bool(descriptor.get("online", True)),
                    load=float(metrics["load"]),
                    active_jobs=int(metrics["active_jobs"]),
                    queue_depth=int(metrics["queue_depth"]),
                    latency_ms=(
                        float(server["latency_ms"])
                        if server.get("latency_ms") not in {None, ""}
                        else None
                    ),
                ))
        return result

    def find(
        self,
        *,
        server_id: str = "",
        port: int | None = None,
        branch: str = "",
        feature: str = "",
        online_only: bool = True,
    ) -> ServiceRoute:
        all_routes = self.routes(include_offline=True)
        candidates = all_routes
        if server_id:
            candidates = [item for item in candidates if item.server_id == server_id]
        if port is not None:
            candidates = [item for item in candidates if item.port == int(port)]
        if branch:
            candidates = [item for item in candidates if item.branch == branch]
        if feature:
            candidates = [item for item in candidates if feature in item.features]
        if not candidates:
            raise TargetNotFound("no registered service matches the target")
        if online_only:
            online = [item for item in candidates if item.online]
            if not online:
                identity = server_id or branch or feature or (f"port {port}" if port else "target")
                raise TargetUnavailable(f"target {identity} is offline")
            candidates = online
        return sorted(
            candidates,
            key=lambda item: (
                float(item.latency_ms)
                if item.latency_ms is not None else float("inf"),
                float(item.load),
                int(item.queue_depth),
                item.server_id,
                item.port,
            ),
        )[0]

    def has_offline_match(
        self,
        *,
        server_id: str = "",
        port: int | None = None,
        branch: str = "",
        feature: str = "",
    ) -> bool:
        try:
            self.find(
                server_id=server_id,
                port=port,
                branch=branch,
                feature=feature,
                online_only=False,
            )
        except TargetNotFound:
            return False
        return True


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
    ) -> dict[str, object]:
        """Query one peer's local job projection through its 7998 Manager.

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

    def artifact_ticket(
        self,
        route: ServiceRoute,
        *,
        job_id: str,
        name: str,
        principal: str,
        preview: bool = False,
        archive: bool = False,
    ) -> dict[str, object]:
        """Ask the owning Manager to mint a ticket for its 7997 data plane."""
        if not route.remote or not route.proxy_token:
            raise ValueError("invalid federated service route")
        payload = json.dumps({
            "server_id": route.server_id,
            "job_id": str(job_id),
            "name": str(name),
            "principal": str(principal),
            "preview": bool(preview),
            "archive": bool(archive),
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._peer_url(route, "/api/federation/artifact-ticket"),
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
                raw = response.read(1024 * 1024)
                status = response.status
        except HTTPError as exc:
            raw = exc.read(1024 * 1024)
            status = exc.code
        except (URLError, OSError) as exc:
            raise ConnectionError("federated artifact service is unavailable") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectionError("federated artifact ticket response is invalid") from exc
        if not isinstance(value, dict):
            raise ConnectionError("federated artifact ticket response is invalid")
        if not 200 <= status < 300:
            raise ConnectionError(
                str(value.get("error") or f"artifact ticket returned HTTP {status}")
            )
        ticket = str(value.get("ticket") or "").strip()
        if not ticket:
            raise ConnectionError("federated artifact response has no ticket")
        # The owning Manager signs the capability, but its own loopback 7997
        # endpoint is not necessarily reachable from this Manager.  Rebuild
        # the URL from the endpoint advertised in this requester's registry;
        # reverse-tunnel deployments use a peer-local port such as 17997.
        endpoint = route.artifact_endpoint or artifact_data_endpoint(
            endpoint=route.endpoint,
            port=route.artifact_port,
        )
        value["data_endpoint"] = endpoint
        value["url"] = artifact_data_url(
            endpoint,
            job_id=job_id,
            name="__archive__" if archive else name,
            ticket=ticket,
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
        """Pull this peer's relevant control events through Manager 7998."""
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
        """Open an SSE stream through the peer Manager's 7998 endpoint."""
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


class FederationSyncWorker:
    """Continuously pull relevant Manager events without opening a new port."""

    def __init__(
        self,
        *,
        server_id: str,
        job_index: Any,
        gateway: FederatedGateway,
        peer_provider: Callable[[], list[dict[str, object]]],
        local_refresh: Callable[[], None] | None = None,
        interval: float = 5.0,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        self.job_index = job_index
        self.gateway = gateway
        self.peer_provider = peer_provider
        self.local_refresh = local_refresh
        self.interval = max(2.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_report: list[dict[str, object]] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-manager-federation-control-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None

    def set_interval(self, interval: float) -> None:
        """Change the next polling interval without restarting the worker."""
        self.interval = max(2.0, min(300.0, float(interval)))

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": bool(self._thread and self._thread.is_alive()),
                "interval": self.interval,
                "last_report": [dict(item) for item in self._last_report],
            }

    @staticmethod
    def _route(peer: dict[str, object]) -> ServiceRoute:
        transfer_node = peer.get("transfer_node")
        transfer_node = transfer_node if isinstance(transfer_node, dict) else {}
        return ServiceRoute(
            server_id=str(peer.get("server_id") or ""),
            role=str(peer.get("role") or ""),
            branch=str(peer.get("branch") or ""),
            revision=str(peer.get("revision") or ""),
            port=7998,
            endpoint=str(peer.get("endpoint") or "").rstrip("/"),
            peer_control_endpoint=str(
                transfer_node.get("peer_control_endpoint") or ""
            ).rstrip("/"),
            peer_data_endpoint=str(
                transfer_node.get("peer_data_endpoint") or ""
            ).rstrip("/"),
            proxy_token=str(peer.get("proxy_token") or ""),
            remote=True,
            online=bool(peer.get("online", True)),
        )

    def sync_once(self) -> list[dict[str, object]]:
        reports: list[dict[str, object]] = []
        if self.local_refresh is not None:
            try:
                self.local_refresh()
            except Exception as exc:
                reports.append({
                    "server_id": self.server_id,
                    "status": "local_refresh_error",
                    "error": str(exc),
                })
        try:
            peers = list(self.peer_provider() or [])
        except Exception as exc:
            reports.append({"status": "error", "error": str(exc)})
            with self._lock:
                self._last_report = reports
            return reports
        for peer in peers:
            peer_id = str(peer.get("server_id") or "").strip()
            if not peer_id or peer_id == self.server_id:
                continue
            route = self._route(peer)
            if not route.online:
                reports.append({
                    "server_id": peer_id,
                    "status": "offline",
                })
                continue
            cursor = self.job_index.sync_cursor(peer_id)
            try:
                value = self.gateway.sync_events(
                    route,
                    requester_server_id=self.server_id,
                    after_sequence=cursor,
                )
                events = [
                    item for item in (value.get("events") or [])
                    if isinstance(item, dict)
                ]
                applied = self.job_index.apply_events(events)
                next_sequence = max(
                    cursor,
                    int(value.get("next_sequence") or cursor),
                )
                self.job_index.advance_sync_cursor(peer_id, next_sequence)
                reports.append({
                    "server_id": peer_id,
                    "status": "ok",
                    "received": len(events),
                    "applied": applied,
                    "next_sequence": next_sequence,
                    "has_more": bool(value.get("has_more")),
                })
            except (ConnectionError, OSError, TypeError, ValueError) as exc:
                reports.append({
                    "server_id": peer_id,
                    "status": "error",
                    "error": str(exc),
                })
        with self._lock:
            self._last_report = reports
        return reports

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # pragma: no cover - defensive daemon guard
                print(f"[federation] control sync failed: {exc}", flush=True)
            self._stop.wait(self.interval)


class FederationAnnouncer:
    """Register a feature Manager to the remote control-plane Manager."""

    def __init__(
        self,
        *,
        register_url: str,
        registration_token: str,
        payload_factory: Callable[[], dict[str, object]],
        response_handler: Callable[[dict[str, object]], None] | None = None,
        transport: FederationTransport | None = None,
        interval: float = 10.0,
    ) -> None:
        self.register_url = register_url.rstrip("/")
        self.registration_token = registration_token
        self.payload_factory = payload_factory
        self.response_handler = response_handler
        self.transport = transport or FederationTransport()
        self.interval = max(3.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-manager-federation-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None

    def _post(self) -> None:
        payload = self.payload_factory()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.register_url,
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.registration_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        with self.transport.open(request, timeout=10) as response:
            raw = response.read(1024 * 1024)
        if self.response_handler is not None:
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict):
                value["_roundtrip_ms"] = round(
                    max(0.0, time.monotonic() - started) * 1000, 2,
                )
                self.response_handler(value)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._post()
            except (OSError, URLError, HTTPError, ValueError, TypeError) as exc:
                print(f"[federation] registration unavailable: {exc}", flush=True)
            self._stop.wait(self.interval)
