"""Validation for schema-v2 research Graph definition contracts."""

from __future__ import annotations

from typing import Any


_ANCHOR_KINDS = {
    "node_entry",
    "node_action",
    "edge",
    "system_gate",
    "coordination",
}
_CONTENT_KINDS = {"sentence", "list", "table", "figure"}
_POLICY_KINDS = {"continuation_reentry", "node_reentry", "evidence_admission"}
_ENTRY_GATE_POLICIES = {
    "discover_before_exit",
    "plan_before_exit",
    "resolve_before_exit",
}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _unique_ids(items: Any, field: str, location: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{location} must be an array of objects")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identifier = str(item.get(field) or "").strip()
        if not identifier:
            raise ValueError(f"every {location} item requires {field}")
        if identifier in result:
            raise ValueError(f"duplicate {location} id: {identifier}")
        result[identifier] = item
    return result


def _require_known_refs(
    values: Any,
    known: set[str],
    *,
    location: str,
) -> None:
    if not _text_list(values):
        raise ValueError(f"{location} must contain ids")
    missing = sorted(set(values) - known)
    if missing:
        raise ValueError(f"{location} references unknown ids: {', '.join(missing)}")


def _validate_change_manifest(graph: dict[str, Any]) -> None:
    value = graph.get("change_manifest")
    if not isinstance(value, dict):
        raise ValueError("schema-v2 graph requires change_manifest")
    if value.get("parent_version") != graph.get("parent_version"):
        raise ValueError("change_manifest parent_version mismatch")
    if not _text(value.get("summary_zh")):
        raise ValueError("change_manifest summary_zh is required")
    changes = _unique_ids(value.get("changes"), "change_id", "change_manifest changes")
    for change_id, item in changes.items():
        if not all(_text(item.get(field)) for field in ("change_kind", "subject_ref", "impact_zh")):
            raise ValueError(f"invalid change_manifest item: {change_id}")


def _validate_catalog(
    graph: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog = graph.get("requirement_catalog")
    if not isinstance(catalog, dict) or int(catalog.get("catalog_revision") or 0) < 1:
        raise ValueError("schema-v2 graph requires versioned requirement_catalog")
    categories = _unique_ids(catalog.get("categories"), "category_id", "requirement categories")
    for category_id, item in categories.items():
        if not _text(item.get("title_zh")) or not _text(item.get("description_zh")):
            raise ValueError(f"invalid requirement category: {category_id}")
    requirements = _unique_ids(
        catalog.get("requirements"), "requirement_id", "entry requirements"
    )
    descriptors = set(graph.get("capability_descriptors") or {})
    for requirement_id, item in requirements.items():
        category_id = str(item.get("category_id") or "")
        if category_id not in categories:
            raise ValueError(f"unknown category for entry requirement: {requirement_id}")
        if int(item.get("revision") or 0) < 1:
            raise ValueError(f"entry requirement revision is required: {requirement_id}")
        if str(item.get("gate_policy") or "") not in _ENTRY_GATE_POLICIES:
            raise ValueError(f"invalid entry requirement gate_policy: {requirement_id}")
        for field in (
            "title_zh",
            "question_zh",
            "select_when_zh",
            "industry_principle_zh",
            "fallback_route",
        ):
            if not _text(item.get(field)):
                raise ValueError(f"{field} is required: {requirement_id}")
        for field in (
            "evidence_expected_zh",
            "not_sufficient_zh",
            "industry_basis_refs",
            "resolver_capability_ids",
            "cli_invocation_templates",
            "report_requirement_refs",
        ):
            if not _text_list(item.get(field)):
                raise ValueError(f"{field} must contain text: {requirement_id}")
        if not item["resolver_capability_ids"]:
            raise ValueError(f"resolver capability is required: {requirement_id}")
        missing = sorted(set(item["resolver_capability_ids"]) - descriptors)
        if missing:
            raise ValueError(
                f"entry requirement resolver descriptors missing: {', '.join(missing)}"
            )
        if not isinstance(item.get("resolver_output_schema"), dict):
            raise ValueError(f"resolver_output_schema is required: {requirement_id}")
    return categories, requirements


def _validate_methods(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    methods = graph.get("report_method_descriptors")
    if not isinstance(methods, dict) or not methods:
        raise ValueError("schema-v2 graph requires report_method_descriptors")
    for method_id, item in methods.items():
        if not _text(method_id) or not isinstance(item, dict):
            raise ValueError("invalid report method descriptor")
        if not _text(item.get("description_zh")):
            raise ValueError(f"report method description is required: {method_id}")
        allowed = item.get("allowed_content")
        if not _text_list(allowed) or not set(allowed) <= _CONTENT_KINDS:
            raise ValueError(f"invalid report method content kinds: {method_id}")
        digest = str(item.get("descriptor_hash") or "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"invalid report method descriptor hash: {method_id}")
    return methods


def _validate_reports(
    graph: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    methods: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    reports = _unique_ids(
        graph.get("report_requirements"), "report_requirement_id", "report requirements"
    )
    node_ids = {str(item["node_id"]) for item in graph["nodes"]}
    edge_ids = {str(item["edge_id"]) for item in graph["edges"]}
    for report_id, item in reports.items():
        anchor_kind = str(item.get("anchor_kind") or "")
        anchor_ref = str(item.get("anchor_ref") or "")
        if anchor_kind not in _ANCHOR_KINDS:
            raise ValueError(f"invalid report anchor kind: {report_id}")
        if not _text(anchor_ref) or not _text(item.get("title_zh")):
            raise ValueError(f"report anchor/title is required: {report_id}")
        if anchor_kind.startswith("node_") and anchor_ref not in node_ids:
            raise ValueError(f"report requirement references unknown node: {report_id}")
        if anchor_kind == "edge" and anchor_ref not in edge_ids:
            raise ValueError(f"report requirement references unknown edge: {report_id}")
        if str(item.get("method_ref") or "") not in methods:
            raise ValueError(f"report requirement references unknown method: {report_id}")
        if not isinstance(item.get("subject_selector"), dict):
            raise ValueError(f"report subject_selector is required: {report_id}")
        requirement_ref = str(item.get("requirement_ref") or "")
        coordination_ref = str(item.get("coordination_ref") or "")
        if bool(requirement_ref) == bool(coordination_ref):
            raise ValueError(
                f"report requirement needs exactly one semantic binding: {report_id}"
            )
        if requirement_ref and requirement_ref not in requirements:
            raise ValueError(f"report requirement references unknown entry requirement: {report_id}")
    return reports


def _validate_anchors(
    graph: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
) -> None:
    requirement_ids = set(requirements)
    report_ids = set(reports)
    for node in graph["nodes"]:
        node_id = str(node["node_id"])
        _require_known_refs(
            node.get("entry_requirement_refs"), requirement_ids,
            location=f"node {node_id} entry_requirement_refs",
        )
        for field in ("entry_report_refs", "node_report_refs"):
            _require_known_refs(node.get(field), report_ids, location=f"node {node_id} {field}")
            if not node[field]:
                raise ValueError(f"node {node_id} requires {field}")
    for edge in graph["edges"]:
        edge_id = str(edge["edge_id"])
        _require_known_refs(
            edge.get("report_requirement_refs"), report_ids,
            location=f"edge {edge_id} report_requirement_refs",
        )
        if not edge["report_requirement_refs"]:
            raise ValueError(f"edge {edge_id} requires report_requirement_refs")
    for requirement_id, item in requirements.items():
        _require_known_refs(
            item["report_requirement_refs"], report_ids,
            location=f"entry requirement {requirement_id} report_requirement_refs",
        )


def _validate_system_policies(graph: dict[str, Any], reports: set[str]) -> None:
    policies = _unique_ids(
        graph.get("system_transition_policies"), "policy_id", "system transition policies"
    )
    if not policies:
        raise ValueError("schema-v2 graph requires system_transition_policies")
    for policy_id, item in policies.items():
        if str(item.get("policy_kind") or "") not in _POLICY_KINDS:
            raise ValueError(f"invalid system transition policy kind: {policy_id}")
        _require_known_refs(
            item.get("report_requirement_refs"), reports,
            location=f"system policy {policy_id} report_requirement_refs",
        )


def validate_graph_contract_extensions(graph: dict[str, Any]) -> None:
    """Validate immutable schema-v2 catalog, reporting, and gate contracts."""
    _validate_change_manifest(graph)
    _, requirements = _validate_catalog(graph)
    methods = _validate_methods(graph)
    reports = _validate_reports(graph, requirements, methods)
    _validate_anchors(graph, requirements, reports)
    _validate_system_policies(graph, set(reports))
