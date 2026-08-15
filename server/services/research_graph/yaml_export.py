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


_RUNTIME_FIELDS = frozenset({"created_by", "created_at"})
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def graph_definition(graph: dict[str, Any]) -> dict[str, Any]:
    """Return the validated protocol definition without SQLite metadata."""
    if not isinstance(graph, dict):
        raise ValueError("research graph must be an object")
    value = deepcopy(graph)
    for field in _RUNTIME_FIELDS:
        value.pop(field, None)
    return validate_graph(value)


def graph_yaml_bytes(graph: dict[str, Any]) -> bytes:
    """Serialize one verified graph version as stable, UTF-8 YAML."""
    definition = graph_definition(graph)
    rendered = yaml.safe_dump(
        definition,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
        width=120,
    )
    return rendered.encode("utf-8")


def graph_yaml_filename(graph: dict[str, Any]) -> str:
    """Build a safe, content-identifying filename for a graph download."""
    definition = graph_definition(graph)
    graph_id = _SAFE_FILENAME.sub("-", str(definition["graph_id"])).strip(".-")
    graph_id = graph_id or "research-graph"
    content_hash = str(definition["content_hash"])
    version = int(definition["version"])
    return f"{graph_id}-v{version}-{content_hash[:16]}.yaml"


__all__ = ["graph_definition", "graph_yaml_bytes", "graph_yaml_filename"]
