"""Best-effort upload after a local report HEAD becomes durable."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from .projection import build_upload_projection


def sync_manager(paths: dict[str, Path]) -> None:
    """Upload content; a Manager outage never rolls back the local report."""
    try:
        snapshot = _load_snapshot(paths)
        projection = build_upload_projection(snapshot)
        payload = json.dumps({
            "report_id": projection["report_id"],
            "owner_ref": _owner_ref(paths),
            "projection": projection,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            "http://127.0.0.1:7998/api/public-research/sync",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2.0) as response:
            response.read(1024)
    except (OSError, ValueError):
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


def _load_snapshot(paths: dict[str, Path]) -> dict[str, object]:
    from ..authoring.tree_projection import project_snapshot
    from ..authoring.tree_store import load_head

    head = load_head(paths)
    return project_snapshot(paths, head)
