"""Small contract for localized Research Graph display text.

Presentation text is a display overlay.  It identifies the Graph version and
locale, but it is not a second semantic Graph and therefore has no content
hash or revision chain.  Missing node/edge labels simply fall back to the
canonical Graph text in the clients.
"""

from __future__ import annotations

from typing import Any, Mapping


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
    "schema_version", "graph_id", "version", "locale", "title",
    "description", "nodes", "edges", "capability_descriptions", "wildcard",
})
_NODE_KEYS = frozenset({"label", "purpose", "entry_evidence", "exit_evidence"})
_EDGE_KEYS = frozenset({"label", "description"})


def normalize_graph_locale(value: Any) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_GRAPH_LOCALE
    raw = str(value).strip()
    normalized = _LOCALE_ALIASES.get(raw.lower())
    if normalized is None:
        supported = ", ".join(SUPPORTED_GRAPH_LOCALES)
        raise ValueError(
            f"unsupported research graph locale: {raw} ({supported})"
        )
    return normalized


def validate_presentation(
    graph: Mapping[str, Any],
    presentation: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one display overlay without creating another Graph identity."""
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
    schema_version = presentation.get(
        "schema_version", PRESENTATION_SCHEMA_VERSION
    )
    if schema_version != PRESENTATION_SCHEMA_VERSION:
        raise ValueError("unsupported research graph presentation schema")
    if str(presentation.get("graph_id") or "") != str(
        graph.get("graph_id") or ""
    ):
        raise ValueError("presentation graph_id does not match Graph version")
    if int(presentation.get("version") or 0) != int(
        graph.get("version") or 0
    ):
        raise ValueError("presentation version does not match Graph version")

    value: dict[str, Any] = {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "graph_id": str(graph["graph_id"]),
        "version": int(graph["version"]),
        "locale": normalize_graph_locale(presentation.get("locale")),
        "title": _required_text(presentation.get("title"), "presentation title"),
        "nodes": _validate_nodes(
            presentation.get("nodes", {}),
            _graph_ids(graph.get("nodes"), "node_id", "Graph nodes"),
        ),
        "edges": _validate_edges(
            presentation.get("edges", {}),
            _graph_ids(graph.get("edges"), "edge_id", "Graph edges"),
        ),
        "capability_descriptions": _validate_text_map(
            presentation.get("capability_descriptions", {}),
            "capability_descriptions",
        ),
    }
    description = presentation.get("description")
    if description is not None:
        value["description"] = _required_text(
            description, "presentation description"
        )
    wildcard = presentation.get("wildcard")
    if wildcard is not None:
        if not isinstance(wildcard, Mapping):
            raise ValueError("presentation wildcard must be an object")
        value["wildcard"] = {
            "label": _required_text(wildcard.get("label"), "wildcard label"),
            "purpose": _required_text(
                wildcard.get("purpose"), "wildcard purpose"
            ),
        }
    return value


def _validate_nodes(
    value: Any,
    graph_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("presentation nodes must be an object")
    result: dict[str, dict[str, Any]] = {}
    for node_id, item in value.items():
        node_id = str(node_id)
        if node_id not in graph_ids:
            raise ValueError(f"presentation node {node_id} is not in Graph")
        if not isinstance(item, Mapping):
            raise ValueError(f"presentation node {node_id} must be an object")
        unknown = sorted(set(item) - _NODE_KEYS)
        if unknown:
            raise ValueError(
                f"presentation node {node_id} has unknown fields: "
                + ", ".join(str(field) for field in unknown)
            )
        translated = {"label": _required_text(
            item.get("label"), f"node {node_id} label"
        )}
        for field in ("purpose",):
            if field in item:
                translated[field] = _required_text(
                    item[field], f"node {node_id} {field}"
                )
        for field in ("entry_evidence", "exit_evidence"):
            if field in item:
                translated[field] = _string_list(
                    item[field], f"node {node_id} {field}"
                )
        result[node_id] = translated
    return result


def _validate_edges(
    value: Any,
    graph_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("presentation edges must be an object")
    result: dict[str, dict[str, Any]] = {}
    for edge_id, item in value.items():
        edge_id = str(edge_id)
        if edge_id not in graph_ids:
            raise ValueError(f"presentation edge {edge_id} is not in Graph")
        if not isinstance(item, Mapping):
            raise ValueError(f"presentation edge {edge_id} must be an object")
        unknown = sorted(set(item) - _EDGE_KEYS)
        if unknown:
            raise ValueError(
                f"presentation edge {edge_id} has unknown fields: "
                + ", ".join(str(field) for field in unknown)
            )
        translated = {"label": _required_text(
            item.get("label"), f"edge {edge_id} label"
        )}
        if "description" in item:
            translated["description"] = _required_text(
                item["description"], f"edge {edge_id} description"
            )
        result[edge_id] = translated
    return result


def _graph_ids(value: Any, key: str, field: str) -> set[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or not str(item.get(key) or ""):
            raise ValueError(f"{field} contain an invalid {key}")
        result.add(str(item[key]))
    return result


def _validate_text_map(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {
        str(key): _required_text(item, f"{field} {key}")
        for key, item in value.items()
    }


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    return [item.strip() for item in value]


__all__ = [
    "DEFAULT_GRAPH_LOCALE",
    "PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_GRAPH_LOCALES",
    "normalize_graph_locale",
    "validate_presentation",
]
