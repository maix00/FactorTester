"""Atomic HEAD publication for report-tree additive transactions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .binding_index import ensure_binding_index
from .tree_batch_validation import validate_batch_operations
from .tree_compaction import discard_unpublished_nodes, prune_displaced_nodes
from .tree_store import load_head, load_node, tree_lock
from .tree_publication import publish_tree_head
from .submission_gate import (
    ReportSubmission,
    validate_publish_lease,
)
from .submission_finalize import mark_submission_published


def mutate(
    paths: dict[str, Path],
    change: Callable[
        [
            dict[str, Path], dict[str, Any], dict[str, Any],
            list[tuple[str, str]], set[str], set[str], set[str],
        ],
        tuple[dict[str, Any], dict[str, Any], list[str]],
    ],
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    with tree_lock(paths):
        previous = load_head(paths)
        validate_publish_lease(paths, previous, submission)
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
                displaced, created, submission,
            )
        except Exception:
            _discard_if_unpublished(paths, previous, created)
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
    submission: ReportSubmission | None = None,
    expected_head: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with tree_lock(paths):
        previous = load_head(paths)
        if expected_head is not None and any(
            previous.get(key) != expected_head.get(key)
            for key in ("report_id", "generation", "root_ref")
        ):
            raise ValueError("report target version changed; rebuild the copy preview")
        validate_publish_lease(paths, previous, submission)
        head = deepcopy(previous)
        root = load_node(paths, previous["root_ref"])
        pending: list[tuple[str, str]] = []
        pending_bindings: set[str] = set()
        displaced: set[str] = set()
        changed: list[str] = []
        created: set[str] = set()
        try:
            ensure_binding_index(paths, root, previous["generation"])
            validate_batch_operations(paths, previous, root, operations)
            for operation in operations:
                head, root, operation_changed = apply(
                    paths, head, root, operation, pending, pending_bindings,
                    displaced, created,
                )
                changed.extend(operation_changed)
            return publish(
                paths, previous, head, root, changed, pending, pending_bindings,
                displaced, created, submission,
            )
        except Exception:
            _discard_if_unpublished(paths, previous, created)
            raise


def publish(
    paths: dict[str, Path], previous: dict[str, Any], next_head: dict[str, Any],
    root: dict[str, Any], changed: list[str],
    pending_locators: list[tuple[str, str]], pending_bindings: set[str],
    displaced: set[str], created: set[str],
    submission: ReportSubmission | None = None,
) -> dict[str, Any]:
    published = publish_tree_head(
        paths=paths,
        previous=previous,
        next_head=next_head,
        root=root,
        changed=changed,
        created=created,
    )
    mark_submission_published(
        paths, submission=submission, published_head=published,
    )
    root_ref = published["root_ref"]
    if previous["root_ref"] != root_ref:
        displaced.add(previous["root_ref"])
    try:
        prune_displaced_nodes(paths, displaced, root_ref=root_ref)
    except OSError:
        pass
    return published


def _discard_if_unpublished(
    paths: dict[str, Path],
    previous: dict[str, Any],
    created: set[str],
) -> None:
    """Never delete nodes after an ambiguous write made them HEAD-reachable."""
    try:
        current = load_head(paths)
    except (OSError, ValueError):
        return
    if current["generation"] <= previous["generation"]:
        discard_unpublished_nodes(paths, created)
