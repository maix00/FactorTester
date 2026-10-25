"""Read-only Job dispatch overview for the super-admin operations page."""

from __future__ import annotations

from typing import Any

from server.jobs.dispatch.outbox import DispatchOutbox


def _queue(server_id: str, port: int) -> str:
    return f"factortester.jobs.{server_id}.{port}"


def dispatch_overview(state: Any, repository: Any) -> dict[str, Any]:
    server_id = str(getattr(state, "server_id", "") or "local")
    outbox = DispatchOutbox(repository.db_path)
    local_ports = sorted({
        int(wt.port)
        for wt in getattr(state, "worktrees", lambda: [])()
        if int(getattr(wt, "port", 0) or 0) > 0
    })
    local_targets = [
        {
            "port": port,
            "queue": _queue(server_id, port),
            "worker_online": repository.worker_target_online(server_id, port),
        }
        for port in local_ports
    ]
    servers = []
    registry = getattr(state, "federation_registry", None)
    if registry is not None:
        for server in registry.servers(include_offline=True):
            sid = str(server.get("server_id") or "")
            ports = []
            for descriptor in server.get("ports") or ():
                if not isinstance(descriptor, dict):
                    continue
                try:
                    port = int(descriptor.get("port") or 0)
                except (TypeError, ValueError):
                    continue
                if port > 0:
                    ports.append({
                        "port": port,
                        "queue": _queue(sid, port),
                        "worker_online": None,
                    })
            servers.append({
                "server_id": sid,
                "role": str(server.get("role") or ""),
                "online": bool(server.get("online")),
                "is_local": sid == server_id,
                "ports": sorted(ports, key=lambda item: item["port"]),
            })
    # Always include the local server even when no registry row is present.
    if not any(item["server_id"] == server_id for item in servers):
        servers.append({
            "server_id": server_id,
            "role": str(getattr(state, "server_role", "") or ""),
            "online": True,
            "is_local": True,
            "ports": local_targets,
        })
    else:
        for item in servers:
            if item["server_id"] == server_id:
                item["ports"] = local_targets
    return {
        "success": True,
        "server_id": server_id,
        "outbox": outbox.counts(),
        "local_targets": local_targets,
        "servers": sorted(servers, key=lambda item: item["server_id"]),
    }
