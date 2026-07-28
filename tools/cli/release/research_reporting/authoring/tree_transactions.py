"""Atomic HEAD publication for report-tree additive transactions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .binding_index import ensure_binding_index, publish_binding_index
from .tree_batch_validation import validate_batch_operations
from .tree_locators import write_locators
from .tree_compaction import discard_unpublished_nodes, prune_displaced_nodes
from .tree_store import load_head, load_node, store_node, tree_lock, write_head


def mutate(
    paths: dict[str, Path],
    change: Callable[
        [
            dict[str, Path], dict[str, Any], dict[str, Any],
            list[tuple[str, str]], set[str], set[str], set[str],
        ],
        tuple[dict[str, Any], dict[str, Any], list[str]],
    ],
) -> dict[str, Any]:
    with tree_lock(paths):
        previous = load_head(paths)
        pending: list[tuple[str, str]] = []
        pending_bindings: set[str] = set()
        displaced: set[str] = set()
        created: set[str] = set()
        try:
            root = load_node(paths, previous["root_ref"])
            ensure_binding_index(paths, root, previous["generation"])
            next_head, root, changed = change(
                paths, deepcopy(previous), root, pending, pending_bindings,
                displaced, created,
            )
            return publish(
                paths, previous, next_head, root, changed, pending, pending_bindings,
                displaced, created,
            )
        except Exception:
            discard_unpublished_nodes(paths, created)
            raise


def mutate_batch(
    paths: dict[str, Path], operations: list[dict[str, Any]],
    apply: Callable[
        [
            dict[str, Path], dict[str, Any], dict[str, Any], dict[str, Any],
            list[tuple[str, str]], set[str], set[str], set[str],
        ],
        tuple[dict[str, Any], dict[str, Any], list[str]],
    ],
) -> dict[str, Any]:
    with tree_lock(paths):
        previous = load_head(paths)
        head = deepcopy(previous)
        root = load_node(paths, previous["root_ref"])
        pending: list[tuple[str, str]] = []
        pending_bindings: set[str] = set()
        displaced: set[str] = set()
        changed: list[str] = []
        created: set[str] = set()
        try:
            validate_batch_operations(paths, previous, root, operations)
            ensure_binding_index(paths, root, previous["generation"])
            for operation in operations:
                head, root, operation_changed = apply(
                    paths, head, root, operation, pending, pending_bindings,
                    displaced, created,
                )
                changed.extend(operation_changed)
            return publish(
                paths, previous, head, root, changed, pending, pending_bindings,
                displaced, created,
            )
        except Exception:
            discard_unpublished_nodes(paths, created)
            raise


def publish(
    paths: dict[str, Path], previous: dict[str, Any], next_head: dict[str, Any],
    root: dict[str, Any], changed: list[str],
    pending_locators: list[tuple[str, str]], pending_bindings: set[str],
    displaced: set[str], created: set[str],
) -> dict[str, Any]:
    root_ref, _ = store_node(paths, root, created=created)
    generation = previous["generation"] + 1
    next_head.update({
        "generation": generation,
        "root_ref": root_ref,
        "changed_node_ids": list(dict.fromkeys(changed)),
        "locator_generation": generation,
    })
    write_locators(paths, pending_locators, generation)
    publish_binding_index(paths, pending_bindings, generation)
    write_head(paths, next_head)
    if previous["root_ref"] != root_ref:
        displaced.add(previous["root_ref"])
    try:
        prune_displaced_nodes(paths, displaced, root_ref=root_ref)
    except OSError:
        pass
    return next_head
