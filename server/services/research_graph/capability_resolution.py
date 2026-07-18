"""Stateless capability attestations and branch resolution validation."""

from __future__ import annotations

from copy import deepcopy
import sqlite3
import time
from typing import Any

import settings as Settings
from server.services.research_graph.branch.projection import (
    normalize_capability_resolution,
)
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def record_capability_approval(
    *,
    owner_user_id: str,
    capability_id: str,
    descriptor_hash: str,
    product_group: str,
    actor: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    del (
        owner_user_id,
        capability_id,
        descriptor_hash,
        product_group,
        actor,
        evidence_refs,
    )
    raise RuntimeError(
        "server capability approvals are retired; approve Skill execution "
        "in the Agent conversation and retain the actual-use audit locally"
    )


def issue_capability_receipt(
    *,
    owner_user_id: str,
    graph_id: str,
    graph_version: int,
    node_id: str,
    product_group: str,
    catalog_hash: str,
    product_profile_hash: str,
    resolver_version: str,
    semantic_resolution: dict[str, Any],
    approval_refs: dict[str, str],
    provider_conformance_hash: str,
    shadow_mode: bool = False,
) -> dict[str, Any]:
    for field, value in (
        ("catalog_hash", catalog_hash),
        ("product_profile_hash", product_profile_hash),
        ("provider_conformance_hash", provider_conformance_hash),
    ):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"{field} must be sha256")
    if not resolver_version:
        raise ValueError("resolver_version is required")
    if not isinstance(approval_refs, dict):
        raise ValueError("approval_refs must be an object")
    if approval_refs:
        raise ValueError(
            "server capability receipts do not accept local approval refs"
        )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=graph_version,
        ) or {}
        if shadow_mode:
            if graph.get("lifecycle") != "draft":
                raise ValueError("shadow receipt requires a draft graph")
            receipt_mode = "shadow"
        else:
            active = conn.execute(
                """
                SELECT version FROM active_research_graphs WHERE graph_id=?
                """,
                (graph_id,),
            ).fetchone()
            if active is None or int(active["version"]) != int(graph_version):
                raise ValueError("receipt graph version is not active")
            receipt_mode = "live"
        node = next(
            (
                item
                for item in graph.get("nodes") or []
                if str(item.get("node_id") or "") == node_id
            ),
            None,
        )
        if node is None:
            raise ValueError("receipt node is not in the active graph")
        resolution = normalize_capability_resolution(
            semantic_resolution,
            node_id=node_id,
        )
        validate_resolution_against_node(
            graph=graph,
            node=node,
            resolution=resolution,
        )
        signed_payload = {
            "owner_user_id": owner_user_id,
            "graph_id": graph_id,
            "graph_version": int(graph_version),
            "graph_hash": str(graph["content_hash"]),
            "node_id": node_id,
            "product_group": product_group,
            "catalog_hash": catalog_hash,
            "product_profile_hash": product_profile_hash,
            "resolver_version": resolver_version,
            "resolution": resolution,
            "approval_refs": approval_refs,
            "provider_conformance_hash": provider_conformance_hash,
            "receipt_mode": receipt_mode,
        }
        signature = json_hash(signed_payload)
        now = time.time()
    return {
        **signed_payload,
        "resolver_attestation": signature,
        "created_at": now,
    }


def verify_capability_receipt(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    receipt: dict[str, Any],
    graph_id: str,
    graph_version: int,
    node_id: str,
    product_group: str,
    expected_mode: str,
) -> dict[str, Any]:
    signature = str(receipt.get("resolver_attestation") or "")
    signed_payload = {
        key: deepcopy(receipt.get(key))
        for key in (
            "owner_user_id",
            "graph_id",
            "graph_version",
            "graph_hash",
            "node_id",
            "product_group",
            "catalog_hash",
            "product_profile_hash",
            "resolver_version",
            "resolution",
            "approval_refs",
            "provider_conformance_hash",
            "receipt_mode",
        )
    }
    if (
        signed_payload["owner_user_id"] != owner_user_id
        or signed_payload["graph_id"] != graph_id
        or int(signed_payload["graph_version"] or 0) != int(graph_version)
        or signed_payload["node_id"] != node_id
        or signed_payload["product_group"] != product_group
        or signed_payload["receipt_mode"] != expected_mode
        or signature != json_hash(signed_payload)
    ):
        raise ValueError("valid server capability receipt is required")
    graph = load_graph_from_conn(
        conn,
        graph_id=graph_id,
        version=graph_version,
    ) or {}
    if signed_payload["graph_hash"] != graph.get("content_hash"):
        raise ValueError("valid server capability receipt is required")
    node = next(
        (
            item
            for item in graph.get("nodes") or []
            if str(item.get("node_id") or "") == node_id
        ),
        None,
    )
    if node is None:
        raise ValueError("capability receipt node is missing")
    resolution = normalize_capability_resolution(
        signed_payload["resolution"] or {},
        node_id=node_id,
    )
    validate_resolution_against_node(
        graph=graph,
        node=node,
        resolution=resolution,
    )
    return resolution


def validate_resolution_against_node(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    resolution: dict[str, Any],
) -> None:
    allowed_ids = set(node.get("required_capabilities") or []) | {
        str(item.get("capability_id") or "")
        for item in node.get("conditional_capabilities") or []
    }
    descriptors = graph.get("capability_descriptors") or {}
    for key in ("bindings", "triggered_conditional_bindings"):
        for binding in resolution.get(key) or []:
            capability_id = str(binding.get("capability_id") or "")
            expected = descriptors.get(capability_id)
            if capability_id not in allowed_ids or binding != {
                "capability_id": capability_id,
                "capability_description": (
                    expected.get("capability_description")
                    if expected
                    else None
                ),
                "descriptor_hash": (
                    expected.get("descriptor_hash") if expected else None
                ),
            }:
                raise ValueError(
                    f"capability descriptor mismatch: {capability_id}"
                )


def missing_required_capabilities(
    node: dict[str, Any],
    resolution: dict[str, Any],
) -> list[str]:
    bound_capabilities = {
        str(item.get("capability_id") or "")
        for key in ("bindings", "triggered_conditional_bindings")
        for item in resolution.get(key) or []
        if isinstance(item, dict)
    }
    return sorted(
        set(node.get("required_capabilities") or []) - bound_capabilities
    )
