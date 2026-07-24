"""Minimal loopback client for the local process Manager."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_TOKEN_ENV = "GTHT_MANAGER_CAPABILITY_TOKEN"
_PORT_ENV = "GTHT_MANAGER_PORT"


def manager_snapshot(*, timeout: float = 3.0) -> dict[str, Any]:
    payload = _request("/api/worktrees", timeout=timeout)
    instances = [
        _worktree_summary(item)
        for item in payload.get("worktrees", [])
        if isinstance(item, dict)
    ]
    vibe = payload.get("vibe_trading")
    if isinstance(vibe, dict):
        running = bool(vibe.get("running"))
        occupied = bool(vibe.get("port_in_use")) and not running
        instances.append({
            "instance_id": str(vibe.get("instance_id") or ""),
            "label": "Vibe-Trading",
            "branch": "",
            "port": int(vibe.get("port") or 0),
            "running": running,
            "daemon_running": running,
            "port_in_use": bool(vibe.get("port_in_use")),
            "kind": "external_service",
            "status": "running" if running else "occupied" if occupied else "stopped",
            "allowed_actions": ["stop"] if running else [] if occupied else ["start"],
        })
    manager = payload.get("manager")
    addresses = {
        "loopback_ip": "127.0.0.1",
        "lan_ip": "",
    }
    if isinstance(manager, dict):
        addresses["loopback_ip"] = str(
            manager.get("loopback_ip") or "127.0.0.1"
        )
        addresses["lan_ip"] = str(manager.get("lan_ip") or "")
    return {"instances": instances, "addresses": addresses}


def manager_action(
    instance_id: str,
    action: str,
    *,
    timeout: float = 180.0,
) -> dict[str, Any]:
    instance_id = str(instance_id or "").strip()
    action = str(action or "").strip()
    instances = manager_snapshot(timeout=min(timeout, 3.0))["instances"]
    target = next(
        (item for item in instances if item["instance_id"] == instance_id),
        None,
    )
    if target is None:
        raise LookupError("unknown managed instance")
    if action not in target.get("allowed_actions", []):
        raise ValueError("manager action is not allowed for the current state")
    if target["kind"] == "external_service":
        routes = {"start": "/vibe/start", "stop": "/vibe/stop"}
    else:
        routes = {
            "start": "/start",
            "stop": "/stop",
            "restart": "/restart-bundle",
            "restart_api": "/restart-api",
            "restart_bundle": "/restart-bundle",
            "force_stop": "/force-stop",
        }
    route = routes.get(action)
    if route is None:
        raise ValueError("unsupported manager action")
    payload = _request(
        route,
        timeout=timeout,
        form={"instance_id": instance_id},
        respond_async=True,
    )
    if not payload.get("success"):
        raise RuntimeError("manager action failed")
    return {
        "instance_id": instance_id,
        "action": action,
        "submitted": bool(payload.get("submitted", True)),
    }


def _worktree_summary(item: dict[str, Any]) -> dict[str, Any]:
    api_running = bool(item.get("running"))
    daemon_running = bool(item.get("daemon_running"))
    port_in_use = bool(item.get("port_in_use"))
    if api_running and daemon_running:
        status = "running"
        allowed_actions = [
            "stop", "restart", "restart_api", "restart_bundle",
            "force_stop",
        ]
    elif api_running or daemon_running:
        status = "degraded"
        allowed_actions = [
            "stop", "restart", "restart_api", "restart_bundle",
            "force_stop",
        ]
    elif port_in_use:
        status = "occupied"
        allowed_actions = []
    else:
        status = "stopped"
        allowed_actions = ["start"]
    return {
        "instance_id": str(item.get("instance_id") or ""),
        "label": str(item.get("label") or ""),
        "branch": str(item.get("branch") or ""),
        "port": int(item.get("port") or 0),
        "running": api_running,
        "daemon_running": daemon_running,
        "port_in_use": port_in_use,
        "kind": "factortester",
        "status": status,
        "allowed_actions": allowed_actions,
    }


def _request(
    path: str,
    *,
    timeout: float,
    form: dict[str, str] | None = None,
    respond_async: bool = False,
) -> dict[str, Any]:
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError("manager capability is unavailable")
    try:
        port = int(os.environ.get(_PORT_ENV, "7998"))
    except ValueError as exc:
        raise RuntimeError("manager port is invalid") from exc
    body = urlencode(form).encode("utf-8") if form is not None else None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if respond_async:
        headers["Prefer"] = "respond-async"
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("manager returned an invalid response")
    return payload
