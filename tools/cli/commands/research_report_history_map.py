"""Strict manual identity map for one-time report-history migration."""

from __future__ import annotations

import json
from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_schema import (
    identifier,
)


def load_component_hints(
    path: Path | None,
    *,
    episode_ids: set[str],
) -> dict[str, str]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("component map is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "episode_components"}
        or value.get("schema_version") != 1
        or not isinstance(value.get("episode_components"), dict)
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
    return hints
