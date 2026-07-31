"""Transactional compatibility validation for one Graph activation."""

from __future__ import annotations

import time
import uuid
from typing import Any

import orjson

import settings as Settings
from cli_anything.factortester_research.core.successor_graph.resolvers import (
    validate_requirement_resolver_activation,
)
from server.services.research_graph import activation_gate
from server.services.research_graph.branch.continuation import (
    prepare_graph_upgrade_validation,
)
from server.services.research_graph.branch.continuation_store import (
    insert_continuation,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.version_lineage import (
    continuation_lineage_projection,
    load_descendant_lineage,
)
from server.services.research_graph.protocol import json_hash, validate_graph
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


_MAX_VALIDATED_BRANCHES = 256


def record_upgrade_validation(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
    proposal_id: str,
) -> dict[str, Any]:
    """Derive and persist the machine Gate without caller-supplied claims."""
    evidence = derive_upgrade_validation(
        graph_id=graph_id,
        version=version,
        owner_user_id=owner_user_id,
    )
    validation_id = json_hash(evidence)
    gate = activation_gate.load_activation_gate(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
    )
    activation_gate.require_graph_target(
        gate,
        graph_id=graph_id,
        graph_version=version,
        graph_hash=str(evidence["target_graph_hash"]),
    )
    activation_gate.record_activation_validation(
        Settings.CACHE_DB_PATH,
        owner_user_id=owner_user_id,
        case_id=proposal_id,
        validation_summary_hash=validation_id,
    )
    return {
        "validation_id": validation_id,
        "graph_id": graph_id,
        "version": int(version),
        "evidence": evidence,
        "created_at": time.time(),
    }


def derive_upgrade_validation(
    *,
    graph_id: str,
    version: int,
    owner_user_id: str,
) -> dict[str, Any]:
    """Validate schema, lineage and every active branch with rollback."""
    target, lineage = _validated_target(graph_id=graph_id, version=version)
    resolver = validate_requirement_resolver_activation(target)
    if not resolver["passed"]:
        raise ValueError("target Graph requirement resolvers are incomplete")
    branches = _active_branches(
        graph_id=graph_id,
        target_version=version,
        owner_user_id=owner_user_id,
    )
    source_versions: set[int] = set()
    for branch in branches:
        source_versions.add(int(branch["graph_version"]))
        prepared = prepare_graph_upgrade_validation(
            source_instance_id=str(branch["instance_id"]),
            source_branch_id=str(branch["branch_id"]),
            owner=owner_user_id,
            target_graph_version=version,
        )
        _validate_transactional_projection(
            prepared=prepared,
            owner_user_id=owner_user_id,
        )
    return {
        "schema_version": 1,
        "validation_kind": "graph_upgrade",
        "evidence_authority": "server_derived",
        "graph_integrity_passed": True,
        "lineage_passed": True,
        "requirement_resolvers_passed": True,
        "continuation_projection_passed": True,
        "target_graph_hash": str(target["content_hash"]),
        "lineage_path_hash": str(lineage["lineage_path_hash"]),
        "source_versions": sorted(source_versions),
        "validated_branch_count": len(branches),
        "persistent_shadow_count": 0,
        "shadow_cleanup": "transaction_rolled_back",
    }


def _validated_target(
    *,
    graph_id: str,
    version: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        target = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=version,
        )
        if target is None:
            raise KeyError("target Graph version not found")
        if target.get("lifecycle") != "draft":
            raise ValueError("activation target must be an immutable draft")
        protocol_target = {
            key: value
            for key, value in target.items()
            if key not in {"created_by", "created_at"}
        }
        validated = validate_graph(protocol_target)
        active = conn.execute(
            "SELECT version FROM active_research_graphs WHERE graph_id=?",
            (graph_id,),
        ).fetchone()
        source_version = (
            int(active["version"])
            if active is not None
            else int(target.get("parent_version") or 0)
        )
        if source_version < 1:
            raise ValueError("activation target has no validated predecessor")
        lineage = continuation_lineage_projection(
            load_descendant_lineage(
                conn,
                graph_id=graph_id,
                source_version=source_version,
                target_version=version,
            )
        )
    return validated, lineage


def _active_branches(
    *,
    graph_id: str,
    target_version: int,
    owner_user_id: str,
) -> list[dict[str, Any]]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT i.instance_id, i.graph_version, b.branch_id
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b
              ON b.instance_id=i.instance_id
            LEFT JOIN research_work_packages AS w
              ON w.owner=i.owner
             AND w.work_package_id=COALESCE(
                 NULLIF(i.work_package_id, ''), i.instance_id
             )
            WHERE i.owner=? AND i.graph_id=? AND i.mode='live'
              AND i.graph_version<>?
              AND b.is_current_incarnation=1
              AND COALESCE(w.lifecycle, 'active')='active'
            ORDER BY i.created_at, i.instance_id, b.branch_id
            LIMIT ?
            """,
            (
                owner_user_id,
                graph_id,
                int(target_version),
                _MAX_VALIDATED_BRANCHES + 1,
            ),
        ).fetchall()
    if len(rows) > _MAX_VALIDATED_BRANCHES:
        raise ValueError("Graph upgrade exceeds bounded active branch validation")
    return [dict(row) for row in rows]


def _validate_transactional_projection(
    *,
    prepared: dict[str, Any],
    owner_user_id: str,
) -> None:
    instance_id = f"validation-{uuid.uuid4().hex}"
    branch_id = f"validation-{uuid.uuid4().hex}"
    trace_id = f"validation-{uuid.uuid4().hex}"
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            insert_continuation(
                conn,
                prepared=prepared,
                owner=owner_user_id,
                instance_id=instance_id,
                branch_id=branch_id,
                trace_id=trace_id,
                now=time.time(),
            )
            row = load_instance_branch_with_latest_trace(
                conn,
                instance_id=instance_id,
                branch_id=branch_id,
                owner=owner_user_id,
            )
            if row is None:
                raise ValueError("Graph upgrade shadow could not be read back")
            if (
                int(row["graph_version"])
                != int(prepared["target_graph_version"])
                or str(row["current_node"]) != str(prepared["target_node"])
                or str(row["latest_trace_id"]) != trace_id
            ):
                raise ValueError("Graph upgrade shadow projection changed")
            evidence = orjson.loads(row["latest_trace_evidence_json"])
            descriptor = evidence.get("graph_continuation") or {}
            if (
                descriptor.get("validation_kind") != "activation_upgrade"
                or str(descriptor.get("target_graph_hash") or "")
                != str(prepared["target_graph_hash"])
            ):
                raise ValueError("Graph upgrade shadow descriptor is invalid")
        finally:
            conn.rollback()
