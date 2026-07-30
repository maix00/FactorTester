"""Copy-on-write replacement of one existing report component."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .binding_index import binding_exists
from .tree_navigation import node_path, rewrite
from .tree_schema import identifier


def retained_attached_bindings(
    bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep workflow-attached chips while replacing authored rich text.

    Explicit links generated from report text always use the ``reference-``
    identity namespace. Replacing a component may remove or change those
    links, so preflight regenerates them from the new text. All other
    bindings were attached by the research/report workflow and must survive
    an unrelated prose or formatting correction.
    """
    return [
        item for item in bindings
        if not str(item["binding_id"]).startswith("reference-")
    ]


def replace_component(
    paths: dict[str, Path], head: dict[str, Any], root: dict[str, Any],
    component_id: str, kind: str, title: str, body: str, content: Any,
    display_kind: str, bindings: list[dict[str, Any]],
    pending_bindings: set[str], displaced: set[str], created: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    identifier(component_id, "component_id")
    current = node_path(
        paths, root, component_id, head["generation"],
    )[0][-1]
    if component_id == "root" or (kind and kind != current["kind"]):
        raise ValueError("replace cannot change report component kind")
    existing = {item["binding_id"]: item for item in current["bindings"]}
    _validate_reused_bindings(bindings, existing)
    _reserve_binding_ids(
        paths, bindings, head["generation"], pending_bindings,
        reusable=set(existing),
    )

    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        replacement_ids = {item["binding_id"] for item in bindings}
        value.update({
            "title": title, "body": body, "content": content,
            "display_kind": display_kind,
            "bindings": [
                *[
                    item for item in retained_attached_bindings(value["bindings"])
                    if item["binding_id"] not in replacement_ids
                ],
                *bindings,
            ],
        })
        return value

    rewritten, changed, replaced = rewrite(
        paths, root, component_id, head["generation"], mutate, created=created,
    )
    displaced.update(replaced)
    return head, rewritten, [*changed, component_id]


def _validate_reused_bindings(
    bindings: list[dict[str, Any]], existing: dict[str, dict[str, Any]],
) -> None:
    for binding in bindings:
        previous = existing.get(binding["binding_id"])
        if previous is not None and (
            binding["kind"], binding["target_ref"]
        ) != (previous["kind"], previous["target_ref"]):
            raise ValueError("reused binding_id cannot change kind or target_ref")


def _reserve_binding_ids(
    paths: dict[str, Path], bindings: list[dict[str, Any]], generation: int,
    pending: set[str], reusable: set[str],
) -> None:
    for binding in bindings:
        binding_id = binding["binding_id"]
        if binding_id in pending or (
            binding_id not in reusable
            and binding_exists(paths, binding_id, generation)
        ):
            raise ValueError("binding_id already exists")
        pending.add(binding_id)
