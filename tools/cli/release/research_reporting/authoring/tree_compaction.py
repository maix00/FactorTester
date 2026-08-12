"""Prune only copy-on-write nodes displaced by the current mutation."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from .tree_schema import node_reference
from .tree_store import load_node


def prune_displaced_nodes(
    paths: dict[str, Path], references: set[str], *, root_ref: str,
) -> int:
    """Delete known-displaced nodes in ``O(number of replacements)``.

    The report is a proper tree: a child ref has one parent and additive
    mutations replace only nodes on the changed ancestor path. Their prior
    refs cannot remain reachable after HEAD switches, so global compaction
    would make every append grow with report size for no correctness gain.
    """
    reachable = _reachable_candidates(paths, root_ref, references)
    removed = 0
    for reference in references - reachable:
        node_reference(reference)
        path = paths["root"] / reference
        if path.is_file():
            path.unlink()
            removed += 1
            parent = path.parent
            if parent != paths["nodes"] and not any(parent.iterdir()):
                parent.rmdir()
    return removed


def _reachable_candidates(
    paths: dict[str, Path], root_ref: str, candidates: set[str],
) -> set[str]:
    """Protect content-addressed refs reused by the newly published tree."""
    found: set[str] = set()
    visited: set[str] = set()
    pending = [root_ref]
    while pending and found != candidates:
        reference = pending.pop()
        if reference in visited:
            continue
        visited.add(reference)
        if reference in candidates:
            found.add(reference)
        node = load_node(paths, reference)
        pending.extend(child["ref"] for child in node["children"])
    return found


def discard_unpublished_nodes(paths: dict[str, Path], references: set[str]) -> None:
    """Remove nodes first written by a transaction that never published HEAD."""
    for reference in references:
        node_reference(reference)
        path = paths["root"] / reference
        with suppress(OSError):
            if path.is_file():
                path.unlink()
                parent = path.parent
                if parent != paths["nodes"] and not any(parent.iterdir()):
                    parent.rmdir()
