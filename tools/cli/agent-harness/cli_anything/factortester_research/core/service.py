from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ManagedWorktree:
    label: str
    branch: str
    path: str
    port: int
    running: bool
    port_in_use: bool


def fetch_worktrees(*, admin_port: int = 7998, timeout: float = 5.0) -> list[ManagedWorktree]:
    with urlopen(f"http://127.0.0.1:{admin_port}/api/worktrees", timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [
        ManagedWorktree(
            label=str(item.get("label") or ""),
            branch=str(item.get("branch") or ""),
            path=str(item.get("path") or ""),
            port=int(item.get("port") or 0),
            running=bool(item.get("running")),
            port_in_use=bool(item.get("port_in_use")),
        )
        for item in payload.get("worktrees", [])
    ]


def select_worktree(worktrees: list[ManagedWorktree], *, target_port: int = 0, branch: str = "", path: str = "") -> ManagedWorktree:
    matches = worktrees
    if target_port:
        matches = [item for item in matches if item.port == target_port]
    if branch:
        matches = [item for item in matches if item.branch == branch or item.label == branch]
    if path:
        matches = [item for item in matches if item.path == path]
    if not matches:
        raise LookupError("no managed worktree matched the requested target")
    if len(matches) > 1:
        labels = ", ".join(f"{item.branch}@{item.port}" for item in matches)
        raise LookupError(f"ambiguous managed worktree target: {labels}")
    return matches[0]


def post_manager_action(action: str, *, admin_port: int, path: str, target_port: int = 0, timeout: float = 10.0) -> str:
    data: dict[str, Any] = {"path": path}
    if action in {"start", "restart-bundle", "restart-api"}:
        data["port"] = str(target_port)
    body = urlencode(data).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{admin_port}/{action}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.geturl()


def restart_worktree_service(
    *,
    admin_port: int,
    target_port: int = 0,
    branch: str = "",
    path: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    worktrees = fetch_worktrees(admin_port=admin_port)
    target = select_worktree(worktrees, target_port=target_port, branch=branch, path=path)
    actions = [{"action": "restart-bundle", "path": target.path, "port": target.port}]
    if dry_run:
        return {"dry_run": True, "target": target.__dict__, "actions": actions}
    restart_url = post_manager_action(
        "restart-bundle", admin_port=admin_port, path=target.path,
        target_port=target.port, timeout=180.0,
    )
    return {
        "dry_run": False,
        "target": target.__dict__,
        "actions": actions,
        "manager_redirects": [restart_url],
    }
