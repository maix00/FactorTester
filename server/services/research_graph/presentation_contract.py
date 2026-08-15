"""Validation and content addressing for Research Graph presentations.

The presentation is deliberately separate from the semantic Graph document.
Changing a translated label must never change the Graph ``content_hash`` or
create a new execution version.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from server.services.research_graph.protocol import json_hash


PRESENTATION_SCHEMA_VERSION = 1
SUPPORTED_GRAPH_LOCALES = ("zh-Hans", "en")
DEFAULT_GRAPH_LOCALE = "zh-Hans"

_LOCALE_ALIASES = {
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-hans": "zh-Hans",
    "en-us": "en",
    "en-gb": "en",
    "en": "en",
}
_PRESENTATION_KEYS = frozenset({
    "schema_version",
    "graph_id",
    "version",
    "content_hash",
    "locale",
    "title",
    "description",
    "nodes",
    "edges",
    "capability_descriptions",
    "wildcard",
})
_NODE_KEYS = frozenset({
    "label",
    "purpose",
    "entry_evidence",
    "exit_evidence",
})
_EDGE_KEYS = frozenset({"label", "description"})


def normalize_graph_locale(value: Any) -> str:
    """Return the one supported locale identifier or reject it."""
    if value is None or not str(value).strip():
        return DEFAULT_GRAPH_LOCALE
    raw = str(value).strip()
    normalized = _LOCALE_ALIASES.get(raw.lower())
    if normalized is None:
        supported = ", ".join(SUPPORTED_GRAPH_LOCALES)
        raise ValueError(f"unsupported research graph locale: {raw} ({supported})")
    return normalized


def validate_presentation(
    graph: Mapping[str, Any],
    presentation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one complete display overlay for one immutable Graph version."""
    if not isinstance(graph, Mapping):
        raise TypeError("research graph must be an object")
    if not isinstance(presentation, Mapping):
        raise TypeError("research graph presentation must be an object")
    unknown = sorted(set(presentation) - _PRESENTATION_KEYS)
    if unknown:
        raise ValueError(
            "research graph presentation has unknown fields: "
            + ", ".join(str(item) for item in unknown)
        )

    schema_version = presentation.get("schema_version", PRESENTATION_SCHEMA_VERSION)
    if schema_version != PRESENTATION_SCHEMA_VERSION:
        raise ValueError("unsupported research graph presentation schema")
    if str(presentation.get("graph_id") or "") != str(graph.get("graph_id") or ""):
        raise ValueError("presentation graph_id does not match Graph version")
    if int(presentation.get("version") or 0) != int(graph.get("version") or 0):
        raise ValueError("presentation version does not match Graph version")
    if str(presentation.get("content_hash") or "") != str(
        graph.get("content_hash") or ""
    ):
        raise ValueError("presentation content_hash does not match Graph version")

    locale = normalize_graph_locale(presentation.get("locale"))
    title = _required_text(presentation.get("title"), "presentation title")
    description = _optional_text(presentation.get("description"))
    nodes = _validate_nodes(graph.get("nodes"), presentation.get("nodes"))
    edges = _validate_edges(graph.get("edges"), presentation.get("edges"))
    capability_descriptions = _validate_capabilities(
        graph.get("capability_descriptors"),
        presentation.get("capability_descriptions", {}),
    )
    wildcard = _validate_wildcard(presentation.get("wildcard"))

    value: dict[str, Any] = {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "graph_id": str(graph["graph_id"]),
        "version": int(graph["version"]),
        "content_hash": str(graph["content_hash"]),
        "locale": locale,
        "title": title,
        "nodes": nodes,
        "edges": edges,
        "capability_descriptions": capability_descriptions,
    }
    if description is not None:
        value["description"] = description
    if wildcard:
        value["wildcard"] = wildcard
    return value


def presentation_content_hash(presentation: Mapping[str, Any]) -> str:
    """Hash only translated display content, excluding row metadata."""
    value = deepcopy(dict(presentation))
    value.pop("translation_hash", None)
    value.pop("translation_revision", None)
    value.pop("created_by", None)
    value.pop("created_at", None)
    return json_hash(value)


def _validate_nodes(
    graph_nodes: Any,
    presentation_nodes: Any,
) -> dict[str, dict[str, Any]]:
    canonical = _objects_by_id(graph_nodes, "node_id", "Graph nodes")
    if not isinstance(presentation_nodes, Mapping):
        raise ValueError("presentation nodes must be an object")
    _require_exact_keys(canonical, presentation_nodes, "node")
    result: dict[str, dict[str, Any]] = {}
    for node_id, item in presentation_nodes.items():
        if not isinstance(item, Mapping):
            raise ValueError(f"presentation node {node_id} must be an object")
        unknown = sorted(set(item) - _NODE_KEYS)
        if unknown:
            raise ValueError(
                f"presentation node {node_id} has unknown fields: "
                + ", ".join(str(field) for field in unknown)
            )
        node = canonical[str(node_id)]
        value = {"label": _required_text(item.get("label"), f"node {node_id} label")}
        if "purpose" in node:
            value["purpose"] = _required_text(
                item.get("purpose"), f"node {node_id} purpose"
            )
        elif "purpose" in item:
            value["purpose"] = _required_text(
                item.get("purpose"), f"node {node_id} purpose"
            )
        for field in ("entry_evidence", "exit_evidence"):
            if field in item:
                value[field] = _string_list(item[field], f"node {node_id} {field}")
        result[str(node_id)] = value
    return result


def _validate_edges(
    graph_edges: Any,
    presentation_edges: Any,
) -> dict[str, dict[str, Any]]:
    canonical = _objects_by_id(graph_edges, "edge_id", "Graph edges")
    if not isinstance(presentation_edges, Mapping):
        raise ValueError("presentation edges must be an object")
    _require_exact_keys(canonical, presentation_edges, "edge")
    result: dict[str, dict[str, Any]] = {}
    for edge_id, item in presentation_edges.items():
        if not isinstance(item, Mapping):
            raise ValueError(f"presentation edge {edge_id} must be an object")
        unknown = sorted(set(item) - _EDGE_KEYS)
        if unknown:
            raise ValueError(
                f"presentation edge {edge_id} has unknown fields: "
                + ", ".join(str(field) for field in unknown)
            )
        value = {"label": _required_text(item.get("label"), f"edge {edge_id} label")}
        if "description" in item:
            value["description"] = _required_text(
                item.get("description"), f"edge {edge_id} description"
            )
        result[str(edge_id)] = value
    return result


def _validate_capabilities(graph_capabilities: Any, value: Any) -> dict[str, str]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ValueError("capability_descriptions must be an object")
    canonical_ids = set()
    if isinstance(graph_capabilities, Mapping):
        canonical_ids = {str(item) for item in graph_capabilities}
    unknown = sorted(set(value) - canonical_ids) if canonical_ids else []
    if unknown:
        raise ValueError(
            "presentation has unknown capability descriptions: "
            + ", ".join(str(item) for item in unknown)
        )
    return {
        str(capability): _required_text(
            description, f"capability {capability} description"
        )
        for capability, description in value.items()
    }


def _validate_wildcard(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("presentation wildcard must be an object")
    unknown = sorted(set(value) - {"label", "purpose"})
    if unknown:
        raise ValueError(
            "presentation wildcard has unknown fields: "
            + ", ".join(str(item) for item in unknown)
        )
    return {
        "label": _required_text(value.get("label"), "wildcard label"),
        "purpose": _required_text(value.get("purpose"), "wildcard purpose"),
    }


def _objects_by_id(value: Any, key: str, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not str(item.get(key) or ""):
            raise ValueError(f"{label} contain an invalid {key}")
        identifier = str(item[key])
        if identifier in result:
            raise ValueError(f"duplicate {key}: {identifier}")
        result[identifier] = item
    return result


def _require_exact_keys(
    canonical: Mapping[str, Any], value: Mapping[str, Any], label: str
) -> None:
    actual = {str(item) for item in value}
    expected = set(canonical)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise ValueError(
            f"presentation {label} ids do not match Graph: "
            + "; ".join(detail)
        )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "presentation description")


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    return [item.strip() for item in value]


__all__ = [
    "DEFAULT_GRAPH_LOCALE",
    "PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_GRAPH_LOCALES",
    "normalize_graph_locale",
    "presentation_content_hash",
    "validate_presentation",
]
