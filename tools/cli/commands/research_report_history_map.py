"""Strict manual identity map for one-time report-history migration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_schema import (
    identifier,
)


def load_history_map(
    path: Path | None,
    *,
    episode_ids: set[str],
) -> dict[str, Any]:
    if path is None:
        return {
            "episode_components": {},
            "component_parents": {},
            "component_special_kinds": {},
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("component map is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("component map fields are invalid")
    version = value.get("schema_version")
    expected = {
        1: {"schema_version", "episode_components"},
        2: {
            "schema_version", "episode_components",
            "component_parents", "component_special_kinds",
        },
    }.get(version, set())
    if (
        not expected
        or set(value) != expected
        or not isinstance(value.get("episode_components"), dict)
        or (
            version == 2
            and (
                not isinstance(value.get("component_parents"), dict)
                or not isinstance(value.get("component_special_kinds"), dict)
            )
        )
    ):
        raise ValueError("component map fields are invalid")
    hints = {}
    for episode, component in value["episode_components"].items():
        episode_id = str(episode)
        if episode_id not in episode_ids:
            raise ValueError(
                f"component map episode is absent from server history: {episode_id}"
            )
        hints[episode_id] = identifier(component, "component_id")
    if len(set(hints.values())) != len(hints):
        raise ValueError("one report component cannot represent two episodes")
    parents = {
        identifier(component, "component_id"):
        identifier(parent, "parent_component_id")
        for component, parent in (
            value.get("component_parents") or {}
        ).items()
    }
    special = {
        identifier(component, "component_id"): str(display_kind)
        for component, display_kind in (
            value.get("component_special_kinds") or {}
        ).items()
    }
    if any(
        display_kind not in {"graph_continuation"}
        for display_kind in special.values()
    ):
        raise ValueError("component special kind is unsupported")
    return {
        "episode_components": hints,
        "component_parents": parents,
        "component_special_kinds": special,
    }


def load_component_hints(
    path: Path | None,
    *,
    episode_ids: set[str],
) -> dict[str, str]:
    """Compatibility helper for callers that only need detour identities."""
    return load_history_map(
        path, episode_ids=episode_ids,
    )["episode_components"]
