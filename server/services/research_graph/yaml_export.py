"""Versioned Research Graph YAML export.

The database JSON remains the canonical, hash-validated representation.  YAML
is deliberately a read-only interchange/download format and never includes
row-level runtime metadata such as the actor or creation timestamp.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

import yaml

from server.services.research_graph.protocol import validate_graph


_RUNTIME_FIELDS = frozenset({
    "created_by", "created_at", "active_pointer", "is_active",
    "presentation", "presentation_locale", "presentation_status",
})
_PRESENTATION_RUNTIME_FIELDS = frozenset({"created_by", "created_at"})
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def graph_definition(graph: dict[str, Any]) -> dict[str, Any]:
    """Return the validated protocol definition without SQLite metadata."""
    if not isinstance(graph, dict):
        raise ValueError("research graph must be an object")
    value = deepcopy(graph)
    for field in _RUNTIME_FIELDS:
        value.pop(field, None)
    return validate_graph(value)


def presentation_definition(presentation: dict[str, Any]) -> dict[str, Any]:
    """Remove SQLite row metadata from a localized presentation bundle."""
    value = deepcopy(presentation)
    for field in _PRESENTATION_RUNTIME_FIELDS:
        value.pop(field, None)
    return value


def graph_yaml_bytes(
    graph: dict[str, Any],
    *,
    presentation: dict[str, Any] | None = None,
) -> bytes:
    """Serialize a canonical Graph or a locale-specific presentation bundle."""
    definition = graph_definition(graph)
    payload: dict[str, Any] = definition
    if presentation is not None:
        payload = {
            "graph": definition,
            "presentation": presentation_definition(presentation),
            "format": "factor-tester.research-graph-presentation.v1",
        }
    rendered = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=120,
    )
    return rendered.encode("utf-8")


def graph_yaml_filename(
    graph: dict[str, Any],
    *,
    presentation: dict[str, Any] | None = None,
) -> str:
    """Build a stable, readable filename for a graph download."""
    definition = graph_definition(graph)
    graph_id = _SAFE_FILENAME.sub("-", str(definition["graph_id"])).strip(".-")
    graph_id = graph_id or "research-graph"
    version = int(definition["version"])
    if presentation is None:
        return f"{graph_id}-v{version}.yaml"
    locale = str(presentation.get("locale") or "locale")
    return f"{graph_id}-v{version}-{locale}.yaml"


__all__ = [
    "graph_definition",
    "graph_yaml_bytes",
    "graph_yaml_filename",
    "presentation_definition",
]
