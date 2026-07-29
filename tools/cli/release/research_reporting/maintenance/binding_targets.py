"""One-time correction of typed bindings degraded by legacy references."""

from __future__ import annotations

from pathlib import Path

from ..authoring.tree_navigation import rewrite
from ..authoring.tree_paths import report_tree_paths
from ..authoring.tree_schema import reference
from ..authoring.tree_transactions import mutate


def rewrite_binding_target(
    *,
    package_root: Path,
    branch_id: str,
    component_id: str,
    binding_id: str,
    expected_target_ref: str,
    target_ref: str,
) -> dict:
    reference(target_ref, "binding.target_ref")
    paths = report_tree_paths(package_root, branch_id)

    def change(
        current, head, root, _pending, _pending_bindings,
        displaced, created,
    ):
        changed_binding = False

        def transform(node):
            nonlocal changed_binding
            for binding in node["bindings"]:
                if binding["binding_id"] != binding_id:
                    continue
                if binding["target_ref"] != expected_target_ref:
                    raise ValueError(
                        "report binding no longer matches migration source"
                    )
                binding["target_ref"] = target_ref
                binding["data"].pop("legacy_target_ref", None)
                changed_binding = True
            if not changed_binding:
                raise ValueError("report binding does not exist")
            return node

        rewritten, changed, replaced = rewrite(
            paths, root, component_id, head["generation"], transform,
            created=created,
        )
        displaced.update(replaced)
        return head, rewritten, [*changed, component_id]

    return mutate(paths, change)
