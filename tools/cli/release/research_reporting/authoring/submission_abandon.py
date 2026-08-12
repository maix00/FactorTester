"""Safely abandon an unpublished report submission and its sidecars."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .submission_pending import digest, load_pending, remove_pending
from .tree_paths import report_tree_paths
from .tree_store import atomic_write, load_head, tree_lock


def abandon_pending_submission(
    *, package_root: Path, branch_id: str,
) -> dict[str, Any]:
    paths = report_tree_paths(package_root, branch_id)
    with tree_lock(paths):
        pending = load_pending(paths)
        if pending is None:
            raise ValueError("report has no pending submission")
        if pending["phase"] == "published":
            raise ValueError(
                "published report submission cannot be abandoned; "
                "use report finalize-pending"
            )
        head = load_head(paths)
        if head["generation"] != pending["base_generation"]:
            raise ValueError(
                "unpublished report submission no longer matches report HEAD"
            )
        restored = _restore_materialized_sidecars(
            package_root=package_root, paths=paths, pending=pending,
        )
        remove_pending(paths)
        return {
            "submission_sequence": pending["submission_sequence"],
            "phase": pending["phase"],
            "logical_identity": pending["logical_identity"],
            "restored_sidecars": restored,
        }


def _restore_materialized_sidecars(
    *, package_root: Path, paths: dict[str, Path], pending: dict[str, Any],
) -> list[str]:
    branch_root = paths["root"].parent
    restored: list[str] = []
    for sidecar in pending["sidecars"]:
        path = branch_root / sidecar["path"]
        current = _read_object(path, sidecar["path"])
        base = _load_git_base(
            package_root=package_root,
            relative_path=path.relative_to(package_root),
            generation=sidecar["base_generation"],
            next_hash=sidecar["next_hash"],
        )
        if current.get("generation") == sidecar["base_generation"]:
            if digest(current) != digest(base):
                raise ValueError(
                    f"pending submission sidecar base conflicts: {sidecar['path']}"
                )
            continue
        if (
            current.get("generation") != sidecar["next_generation"]
            or digest(current) != sidecar["next_hash"]
        ):
            raise ValueError(
                f"pending submission sidecar conflicts: {sidecar['path']}"
            )
        atomic_write(
            path,
            json.dumps(
                base, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode() + b"\n",
        )
        restored.append(sidecar["path"])
    return restored


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"pending submission sidecar is unreadable: {label}"
        ) from error
    if not isinstance(value, dict):
        raise ValueError(f"pending submission sidecar is unreadable: {label}")
    return value


def _load_git_base(
    *, package_root: Path, relative_path: Path, generation: int, next_hash: str,
) -> dict[str, Any]:
    relative = relative_path.as_posix()
    head = _git_json(package_root, f"HEAD:{relative}")
    if isinstance(head, dict) and head.get("generation") == generation:
        return head
    try:
        commits = subprocess.run(
            [
                "git", "-C", str(package_root), "log", "--format=%H",
                "--", relative,
            ],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(
            f"pending submission sidecar Git history is unavailable: {relative}"
        ) from error
    for commit in commits:
        current = _git_json(package_root, f"{commit}:{relative}")
        if not isinstance(current, dict) or digest(current) != next_hash:
            continue
        base = _git_json(package_root, f"{commit}^:{relative}")
        if isinstance(base, dict) and base.get("generation") == generation:
            return base
    raise ValueError(
        f"pending submission sidecar base is unavailable in Git: {relative}"
    )


def _git_json(package_root: Path, object_ref: str) -> dict[str, Any] | None:
    try:
        shown = subprocess.run(
            ["git", "-C", str(package_root), "show", object_ref],
            capture_output=True,
        )
    except OSError:
        return None
    if shown.returncode != 0:
        return None
    try:
        value = json.loads(shown.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
