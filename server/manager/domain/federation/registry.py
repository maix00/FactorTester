"""Persistent server leases and execution-route selection."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

from .models import ServiceRoute, TargetNotFound, TargetUnavailable

REGISTRY_SCHEMA_VERSION = 1
DEFAULT_LEASE_SECONDS = 30.0

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

def _normalise_registration(payload: dict[str, object]) -> dict[str, object]:
    server_id = _string(payload.get("server_id"), field="server_id")
    role = _string(payload.get("role"), field="role")
    if role not in {"main", "feat"}:
        raise ValueError("role must be main or feat")
    endpoint = _string(payload.get("endpoint"), field="endpoint").rstrip("/")
    proxy_token = _string(payload.get("proxy_token"), field="proxy_token")
    ports = _port_descriptors(payload.get("ports"))
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

