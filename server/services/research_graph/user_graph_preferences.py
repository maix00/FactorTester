"""Per-user default Research Graph selection on one Manager."""

from __future__ import annotations

import os
import time
from typing import Any

import settings as Settings
from server.services.research_graph.user_graphs import load_graph_file
from tools.data.sqlite.db import connect_sqlite


_SERVER_ID = str(os.environ.get("FACTORTESTER_SERVER_ID") or "local").strip()


def set_default(
    *,
    owner: str,
    kind: str,
    graph_file_id: str = "",
    graph_id: str = "",
    version: int = 0,
) -> dict[str, Any] | None:
    """Select a user file or server Graph for this Manager/user only."""
    owner = _required(owner, "owner")
    kind = str(kind or "").strip().lower()
    if kind in {"", "none", "clear"}:
        _clear_default(owner)
        return None
    if kind == "user":
        selected = load_graph_file(owner=owner, graph_file_id=graph_file_id)
        if selected is None:
            raise KeyError("user research graph file not found")
        ref = str(graph_file_id)
    elif kind == "server":
        from server.services.research_graph.versions import load_graph

        selected_graph = load_graph(graph_id=str(graph_id), version=int(version))
        if selected_graph is None:
            raise KeyError("server research graph version not found")
        ref = f"{selected_graph['graph_id']}@v{int(selected_graph['version'])}"
    else:
        raise ValueError("default research graph kind must be user, server, or none")

    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO user_research_graph_preferences (
                owner, default_kind, default_ref, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(owner) DO UPDATE SET
                default_kind=excluded.default_kind,
                default_ref=excluded.default_ref,
                updated_at=excluded.updated_at
            """,
            (owner, kind, ref, now),
        )
    return get_default(owner=owner)


def get_default(*, owner: str) -> dict[str, Any] | None:
    owner = _required(owner, "owner")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT default_kind, default_ref, updated_at
            FROM user_research_graph_preferences WHERE owner=?
            """,
            (owner,),
        ).fetchone()
    if row is None:
        return None
    kind = str(row["default_kind"])
    ref = str(row["default_ref"])
    value: dict[str, Any] = {
        "kind": kind,
        "ref": ref,
        "updated_at": float(row["updated_at"]),
        "source_server_id": _SERVER_ID,
        "sync_scope": "manager-local",
    }
    if kind == "user":
        file_value = load_graph_file(owner=owner, graph_file_id=ref)
        if file_value is None:
            _clear_default(owner)
            return None
        value["file"] = file_value
    elif kind == "server":
        graph_id, _, raw_version = ref.rpartition("@v")
        if not graph_id or not raw_version.isdigit():
            _clear_default(owner)
            return None
        from server.services.research_graph.versions import load_graph

        graph = load_graph(graph_id=graph_id, version=int(raw_version))
        if graph is None:
            _clear_default(owner)
            return None
        value["graph"] = graph
    else:
        _clear_default(owner)
        return None
    return value


def _clear_default(owner: str) -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            "DELETE FROM user_research_graph_preferences WHERE owner=?",
            (owner,),
        )


def _required(value: str, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


__all__ = ["get_default", "set_default"]
