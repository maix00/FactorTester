from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ManagedWorktree:
    instance_id: str
    label: str
    branch: str
    port: int
    running: bool
    port_in_use: bool


def manager_capability_token() -> str:
    inline = os.environ.get("GTHT_MANAGER_CAPABILITY_TOKEN", "").strip()
    if inline:
        return inline
    configured = os.environ.get("GTHT_MANAGER_CAPABILITY_FILE", "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
        ).strip()
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = (Path.cwd() / common_path).resolve()
        path = common_path.parent / ".workspace" / "flask-manager" / "manager-capability.key"
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RuntimeError(f"manager capability is unavailable: {path}") from exc
    if not value:
        raise RuntimeError("manager capability is empty")
    return value


def _authorized_request(url: str, *, token: str, data: bytes | None = None) -> Request:
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")


def fetch_worktrees(
    *, admin_port: int = 7998, timeout: float = 5.0,
    capability_token: str = "",
) -> list[ManagedWorktree]:
    request = _authorized_request(
        f"http://127.0.0.1:{admin_port}/api/worktrees",
        token=capability_token or manager_capability_token(),
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [
        ManagedWorktree(
            instance_id=str(item.get("instance_id") or ""),
            label=str(item.get("label") or ""),
            branch=str(item.get("branch") or ""),
            port=int(item.get("port") or 0),
            running=bool(item.get("running")),
            port_in_use=bool(item.get("port_in_use")),
        )
        for item in payload.get("worktrees", [])
    ]


def select_worktree(
    worktrees: list[ManagedWorktree], *, instance_id: str = "",
    target_port: int = 0, branch: str = "",
) -> ManagedWorktree:
    matches = worktrees
    if instance_id:
        matches = [item for item in matches if item.instance_id == instance_id]
    if target_port:
        matches = [item for item in matches if item.port == target_port]
    if branch:
        matches = [item for item in matches if item.branch == branch or item.label == branch]
    if not matches:
        raise LookupError("no managed worktree matched the requested target")
    if len(matches) > 1:
        labels = ", ".join(f"{item.branch}@{item.port}" for item in matches)
        raise LookupError(f"ambiguous managed worktree target: {labels}")
    return matches[0]


def post_manager_action(
    action: str, *, admin_port: int, instance_id: str,
    capability_token: str = "", timeout: float = 10.0,
) -> dict[str, Any]:
    body = urlencode({"instance_id": instance_id}).encode("utf-8")
    request = _authorized_request(
        f"http://127.0.0.1:{admin_port}/{action}",
        token=capability_token or manager_capability_token(),
        data=body,
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(str(payload.get("error") or "manager action failed"))
    return payload


def restart_worktree_service(
    *,
    admin_port: int,
    instance_id: str = "",
    target_port: int = 0,
    branch: str = "",
    dry_run: bool = False,
    capability_token: str = "",
) -> dict[str, Any]:
    token = capability_token or manager_capability_token()
    worktrees = fetch_worktrees(admin_port=admin_port, capability_token=token)
    target = select_worktree(
        worktrees, instance_id=instance_id,
        target_port=target_port, branch=branch,
    )
    actions = [{
        "action": "restart-bundle",
        "instance_id": target.instance_id,
        "port": target.port,
    }]
    if dry_run:
        return {"dry_run": True, "target": target.__dict__, "actions": actions}
    manager_response = post_manager_action(
        "restart-bundle", admin_port=admin_port,
        instance_id=target.instance_id, capability_token=token, timeout=180.0,
    )
    return {
        "dry_run": False,
        "target": target.__dict__,
        "actions": actions,
        "manager_response": manager_response,
    }
