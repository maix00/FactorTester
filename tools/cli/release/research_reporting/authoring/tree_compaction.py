"""Prune only copy-on-write nodes displaced by the current mutation."""

from __future__ import annotations

from pathlib import Path

from .tree_schema import node_reference


def prune_displaced_nodes(
    paths: dict[str, Path], references: set[str], *, root_ref: str,
) -> int:
    """Delete known-displaced nodes in ``O(number of replacements)``.

    The report is a proper tree: a child ref has one parent and additive
    mutations replace only nodes on the changed ancestor path. Their prior
    refs cannot remain reachable after HEAD switches, so global compaction
    would make every append grow with report size for no correctness gain.
    """
    removed = 0
    for reference in references - {root_ref}:
        node_reference(reference)
        path = paths["root"] / reference
        if path.is_file():
            path.unlink()
            removed += 1
            parent = path.parent
            if parent != paths["nodes"] and not any(parent.iterdir()):
                parent.rmdir()
    return removed
