"""Best-effort upload after a local report HEAD becomes durable."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen
from tools.cli.http import HttpClientError

from .projection import build_upload_projection


def sync_manager(paths: dict[str, Path]) -> None:
    """Upload content; a Manager outage never rolls back the local report."""
    try:
        snapshot = _load_snapshot(paths)
        projection = build_upload_projection(snapshot)
        from tools.cli.agent_auth import load_capability
        capability = load_capability()
        if capability is not None:
            from tools.cli.http import HttpSession
            # Reuse the injected Manager endpoint and profile-bound session.
            # /workspace is deliberately not a source of account identity.
            HttpSession(
                capability.base_url, agent_capability=capability,
                bearer_token=capability.token, persist_cookies=False, timeout=2.0,
            ).post("/api/research-publications/sync", {
                "report_id": projection["report_id"],
                "profile_ref": capability.profile_id,
                "build_source": "server_agent",
                "build_source_ref": capability.profile_id,
                "branch_ref": paths["root"].parent.name,
                "projection": projection,
            })
            return
        payload = json.dumps({
            "report_id": projection["report_id"],
            "owner_ref": _owner_ref(paths),
            "profile_ref": _profile_ref(paths),
            "projection": projection,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            "http://127.0.0.1:7998/api/research-publications/sync",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-FactorTester-Client": "cli",
            },
            method="POST",
        )
        with urlopen(request, timeout=2.0) as response:
            response.read(1024)
    except (OSError, ValueError, HttpClientError):
        return


def _owner_ref(paths: dict[str, Path]) -> str:
    parts = paths["root"].parts
    try:
        index = parts.index("users")
        owner = parts[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("report owner cannot be resolved") from exc
    if not owner or owner in {".", ".."}:
        raise ValueError("report owner cannot be resolved")
    return owner


def _profile_ref(paths: dict[str, Path]) -> str:
    parts = paths["root"].parts
    try:
        index = parts.index("profiles")
        profile = parts[index + 1]
    except (ValueError, IndexError):
        return ""
    return profile if profile not in {".", ".."} else ""


def _load_snapshot(paths: dict[str, Path]) -> dict[str, object]:
    from ..authoring.tree_projection import project_snapshot
    from ..authoring.tree_store import load_head

    head = load_head(paths)
    return project_snapshot(paths, head)
