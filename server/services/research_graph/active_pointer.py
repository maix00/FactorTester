"""Exact-hash-controlled Active Graph pointer operations."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import time
from typing import Any

import settings as Settings
from server.services.research_graph import pointer_gate
from server.services.research_graph.protocol import GraphActivationBlocked
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def pointer_reason_hash(reason: str) -> str:
    value = str(reason).strip()
    if not value:
        raise ValueError("pointer change reason is required")
    return hashlib.sha256(value.encode()).hexdigest()


def load_active_graph(*, graph_id: str) -> dict[str, Any] | None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT version, activated_by, activated_at
            FROM active_research_graphs
            WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if row is None:
            return None
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(row["version"]),
        )
    if graph is None:
        raise ValueError("active pointer references a missing Graph version")
    return _with_pointer(graph, row)


def activate_graph(
    *,
    graph_id: str,
    source_version: int,
    actor: str,
    human_authorization_id: str,
) -> dict[str, Any]:
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=source_version,
        )
        if source is None:
            raise KeyError("graph version not found")
        if source["lifecycle"] != "draft":
            raise GraphActivationBlocked("only a draft graph can be activated")
        try:
            pointer_gate.consume_activation(
                conn,
                owner_user_id=actor,
                case_id=human_authorization_id,
                graph_id=graph_id,
                graph_version=source_version,
                graph_hash=str(source["content_hash"]),
                effect_ref=(
                    f"active-graph:{graph_id}@{int(source_version)}:"
                    f"{source['content_hash']}"
                ),
            )
        except KeyError as exc:
            raise GraphActivationBlocked(
                "human activation authorization Gate not found"
            ) from exc
        except ValueError as exc:
            raise GraphActivationBlocked(str(exc)) from exc
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(graph_id) DO UPDATE SET
                version=excluded.version,
                activated_by=excluded.activated_by,
                activated_at=excluded.activated_at
            """,
            (graph_id, int(source_version), actor, now),
        )
    result = _with_pointer(
        source,
        {
            "version": int(source_version),
            "activated_by": actor,
            "activated_at": now,
        },
    )
    return result


def rollback_active_graph(
    *,
    graph_id: str,
    target_version: int,
    actor: str,
    reason: str,
    human_authorization_id: str,
) -> dict[str, Any]:
    reason_value = str(reason).strip()
    reason_hash = pointer_reason_hash(reason_value)
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """
            SELECT version FROM active_research_graphs WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if current is None:
            raise KeyError("active graph not found")
        from_version = int(current["version"])
        if from_version == int(target_version):
            raise ValueError("rollback target is already active")
        target = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=target_version,
        )
        if target is None:
            raise KeyError("rollback target Graph version not found")
        effect_ref = (
            f"graph-pointer-rollback:{graph_id}:"
            f"{from_version}->{int(target_version)}:{reason_hash}"
        )
        try:
            pointer_gate.consume_rollback(
                conn,
                owner_user_id=actor,
                case_id=human_authorization_id,
                graph_id=graph_id,
                from_version=from_version,
                to_version=int(target_version),
                graph_hash=str(target["content_hash"]),
                reason_hash=reason_hash,
                effect_ref=effect_ref,
            )
        except KeyError as exc:
            raise GraphActivationBlocked(
                "human rollback authorization Gate not found"
            ) from exc
        except ValueError as exc:
            raise GraphActivationBlocked(str(exc)) from exc
        cursor = conn.execute(
            """
            UPDATE active_research_graphs
            SET version=?, activated_by=?, activated_at=?
            WHERE graph_id=? AND version=?
            """,
            (
                int(target_version),
                actor,
                now,
                graph_id,
                from_version,
            ),
        )
        if int(cursor.rowcount) != 1:
            raise GraphActivationBlocked(
                "active Graph pointer changed during rollback"
            )
    return {
        "authorization_id": human_authorization_id,
        "effect_ref": effect_ref,
        "graph_id": graph_id,
        "from_version": from_version,
        "to_version": int(target_version),
        "actor": actor,
        "reason": reason_value,
        "reason_hash": reason_hash,
        "active_graph": _with_pointer(
            target,
            {
                "version": int(target_version),
                "activated_by": actor,
                "activated_at": now,
            },
        ),
        "created_at": now,
    }


def _with_pointer(
    graph: dict[str, Any],
    pointer: Any,
) -> dict[str, Any]:
    value = deepcopy(graph)
    value["active_pointer"] = {
        "version": int(pointer["version"]),
        "activated_by": str(pointer["activated_by"]),
        "activated_at": float(pointer["activated_at"]),
    }
    value["is_active"] = True
    return value
