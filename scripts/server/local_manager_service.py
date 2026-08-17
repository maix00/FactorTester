#!/usr/bin/env python3
"""Control one local Manager-owned service through the 7998 API.

This is a host-side operator helper.  It deliberately does not use Docker's
socket and does not expose a new network listener.  Docker lifecycle remains
in ``factortester_container.sh``; service lifecycle remains owned by Manager.
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ManagerServiceError(RuntimeError):
    """A bounded, operator-readable Manager service control failure."""


def _read_capability(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ManagerServiceError(
            f"Manager capability file is unavailable: {path}"
        ) from exc
    if not value:
        raise ManagerServiceError("Manager capability file is empty")
    if any(character.isspace() for character in value):
        raise ManagerServiceError("Manager capability file contains invalid whitespace")
    return value


def _request_json(
    base_url: str,
    token: str,
    path: str,
    *,
    form: dict[str, str] | None = None,
    timeout: float,
) -> dict[str, Any]:
    data = urlencode(form).encode("utf-8") if form is not None else None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method="POST" if form is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout, context=_tls_context(base_url)) as response:
            raw = response.read()
    except HTTPError as exc:
        # Do not echo the response body: it may contain implementation detail
        # or a path from a failed Manager operation.
        raise ManagerServiceError(
            f"Manager request {path} failed with HTTP {exc.code}"
        ) from exc
    except (OSError, URLError) as exc:
        raise ManagerServiceError(
            f"Manager request {path} failed: {exc}"
        ) from exc
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManagerServiceError(
            f"Manager request {path} returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ManagerServiceError(f"Manager request {path} returned an invalid object")
    return value


def _tls_context(base_url: str) -> ssl.SSLContext | None:
    # Local Docker Manager normally uses HTTP on loopback.  Keep HTTPS support
    # usable for an explicitly configured local TLS endpoint without disabling
    # certificate verification.
    if base_url.lower().startswith("https://"):
        return ssl.create_default_context()
    return None


def _target(snapshot: dict[str, Any], port: int) -> dict[str, Any]:
    matches = [
        item for item in snapshot.get("worktrees", ())
        if isinstance(item, dict) and int(item.get("port") or 0) == port
    ]
    if len(matches) != 1:
        if not matches:
            raise ManagerServiceError(f"没有找到端口 {port} 对应的 Manager 服务")
        raise ManagerServiceError(f"端口 {port} 对应多个 Manager 服务")
    instance_id = str(matches[0].get("instance_id") or "").strip()
    if not instance_id:
        raise ManagerServiceError(f"端口 {port} 缺少 Manager 服务身份")
    return matches[0]


def _is_running(item: dict[str, Any]) -> bool:
    return bool(item.get("running") and item.get("daemon_running", True))


def _wait_for_state(
    base_url: str,
    token: str,
    *,
    port: int,
    instance_id: str,
    running: bool,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        snapshot = _request_json(
            base_url,
            token,
            "/api/worktrees",
            timeout=min(5.0, timeout),
        )
        matches = [
            item for item in snapshot.get("worktrees", ())
            if isinstance(item, dict)
            and str(item.get("instance_id") or "") == instance_id
        ]
        if len(matches) == 1:
            item = matches[0]
            if _is_running(item) is running and (
                not running or bool(item.get("port_in_use"))
            ):
                return item
        time.sleep(0.2)
    state = "running" if running else "stopped"
    raise ManagerServiceError(
        f"端口 {port} 在 {timeout:.0f}s 内未恢复为 {state}"
    )


def perform(
    *,
    base_url: str,
    capability_file: Path,
    port: int,
    action: str,
    timeout: float,
) -> dict[str, Any]:
    token = _read_capability(capability_file)
    snapshot = _request_json(
        base_url,
        token,
        "/api/worktrees",
        timeout=min(5.0, timeout),
    )
    target = _target(snapshot, port)
    instance_id = str(target["instance_id"])
    routes = {
        "start": ("/start", True),
        "stop": ("/stop", False),
        "force-stop": ("/force-stop", False),
        "reload-api": ("/restart-api", True),
        "restart-bundle": ("/restart-bundle", True),
    }
    try:
        route, expected_running = routes[action]
    except KeyError as exc:
        raise ManagerServiceError(f"unsupported service action: {action}") from exc
    response = _request_json(
        base_url,
        token,
        route,
        form={"instance_id": instance_id},
        timeout=timeout,
    )
    if not bool(response.get("success", True)):
        raise ManagerServiceError(f"Manager rejected service action: {action}")
    final = _wait_for_state(
        base_url,
        token,
        port=port,
        instance_id=instance_id,
        running=expected_running,
        timeout=timeout,
    )
    return {
        "success": True,
        "action": action,
        "port": port,
        "instance_id": instance_id,
        "running": _is_running(final),
        "message": str(response.get("message") or "service action completed"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager", required=True)
    parser.add_argument("--capability-file", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--action",
        choices=("start", "stop", "force-stop", "reload-api", "restart-bundle"),
        required=True,
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        value = perform(
            base_url=args.manager,
            capability_file=args.capability_file,
            port=args.port,
            action=args.action,
            timeout=args.timeout,
        )
    except ManagerServiceError as exc:
        parser.exit(1, f"error: {exc}\n")
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
