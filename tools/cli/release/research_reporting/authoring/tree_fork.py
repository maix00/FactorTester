"""Snapshot inheritance when one research Graph branch forks another."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .tree_paths import report_tree_paths
from .submission_status import require_no_pending
from .tree_store import load_head, load_node, tree_lock, write_head
from .tree_sqlite_index import ensure_sqlite_index
from ..work_package_identity import ensure_work_package_identity


def fork_report_tree(
    *,
    package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    target_report_id: str,
    reuse_existing: bool = False,
    expected_source_generation: int | None = None,
) -> dict[str, Any]:
    """Clone the source HEAD and immutable nodes into a new branch report."""
    if source_branch_id == target_branch_id:
        raise ValueError("report fork requires a distinct target branch")
    source = report_tree_paths(package_root, source_branch_id)
    target = report_tree_paths(package_root, target_branch_id)
    identity = ensure_work_package_identity(
        package_root,
        work_package_id=Path(package_root).name,
        report_id=target_report_id,
    )
    with tree_lock(source):
        source_head = load_head(source)
        if expected_source_generation is not None and source_head["generation"] != expected_source_generation:
            raise ValueError("report fork source version changed; refresh before retrying")
        require_no_pending(source, source_head)
        with tree_lock(target):
            if target["head"].exists():
                head = load_head(target)
                if not reuse_existing:
                    raise ValueError("target branch report already exists")
                if head["report_id"] != target_report_id:
                    raise ValueError(
                        "existing target branch report identity conflicts"
                    )
                return {
                    "paths": target, "head": head, "inherited": False,
                }
            _copy_assets(
                Path(package_root).resolve(), Path(package_root).resolve(), source_head["assets"],
                source_branch_id, target_branch_id,
            )
            _copy_tree(source["nodes"], target["nodes"])
            if source["binding_registry"].is_file():
                shutil.copy2(
                    source["binding_registry"], target["binding_registry"],
                )
            head = {
                **source_head,
                "report_id": identity["report_id"],
                "changed_node_ids": ["root"],
            }
            write_head(target, head)
            ensure_sqlite_index(
                target, load_node(target, head["root_ref"]),
                head["generation"],
            )
    return {"paths": target, "head": head, "inherited": True}


def inherit_continuation_report_tree(
    *,
    package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    target_report_id: str,
) -> dict[str, Any]:
    """Inherit once and preserve later target-only continuation records."""
    return fork_report_tree(
        package_root=package_root,
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        target_report_id=target_report_id,
        reuse_existing=True,
    )


def inherit_report_tree_across_packages(
    *,
    source_package_root: Path,
    target_package_root: Path,
    source_branch_id: str,
    target_branch_id: str,
    target_report_id: str,
    expected_source_generation: int | None = None,
) -> dict[str, Any]:
    """Clone one branch tree into an isolated continuation Work Package."""
    source_root = Path(source_package_root).expanduser().resolve()
    target_root = Path(target_package_root).expanduser().resolve()
    if source_root == target_root:
        raise ValueError("cross-package report inheritance requires two roots")
    source = report_tree_paths(source_root, source_branch_id)
    target = report_tree_paths(target_root, target_branch_id)
    ensure_work_package_identity(
        source_root,
        work_package_id=source_root.name,
        report_id=str(load_head(source)["report_id"]),
    )
    target_identity = ensure_work_package_identity(
        target_root,
        work_package_id=target_root.name,
        report_id=target_report_id,
    )
    with tree_lock(source):
        source_head = load_head(source)
        if expected_source_generation is not None and source_head["generation"] != expected_source_generation:
            raise ValueError("report fork source version changed; refresh before retrying")
        require_no_pending(source, source_head)
        with tree_lock(target):
            if target["head"].exists():
                head = load_head(target)
                if head["report_id"] != target_report_id:
                    raise ValueError(
                        "existing target branch report identity conflicts"
                    )
                return {
                    "paths": target, "head": head, "inherited": False,
                }
            _copy_assets(source_root, target_root, source_head["assets"], source_branch_id, target_branch_id)
            _copy_tree(source["nodes"], target["nodes"])
            if source["binding_registry"].is_file():
                shutil.copy2(
                    source["binding_registry"], target["binding_registry"],
                )
            head = {
                **source_head,
                "report_id": target_identity["report_id"],
                "changed_node_ids": ["root"],
            }
            write_head(target, head)
            ensure_sqlite_index(
                target, load_node(target, head["root_ref"]),
                head["generation"],
            )
    return {"paths": target, "head": head, "inherited": True}


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _copy_assets(
    source_root: Path, target_root: Path, assets: list[dict],
    source_branch_id: str, target_branch_id: str,
) -> None:
    """Verify all local bytes before publishing an inherited report HEAD.

    Content-addressed destinations avoid overwriting files of another branch.
    External references remain external; unavailable local bytes are an error.
    """
    staged = []
    try:
        for asset in assets:
            relative = asset.get("local_ref")
            if not relative and asset.get("external_ref"):
                continue
            if not relative:
                filename = Path(asset["filename"]).name
                candidates = [source_root / "branches" / source_branch_id / "assets" / filename,
                              source_root / "assets" / filename]
                relative = next((path.relative_to(source_root) for path in candidates if path.is_file()),
                                candidates[0].relative_to(source_root))
            source = (source_root / relative).resolve()
            if not source.is_relative_to(source_root) or not source.is_file():
                raise ValueError("report fork asset is missing or outside its package")
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if asset.get("content_hash") and asset["content_hash"] != digest:
                raise ValueError("report fork asset hash mismatch")
            relative_target = f"branches/{target_branch_id}/assets/{digest}{source.suffix}"
            destination = (target_root / relative_target).resolve()
            if not destination.is_relative_to(target_root):
                raise ValueError("report fork asset destination escapes its package")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as out:
                temporary = Path(out.name)
                staged.append((temporary, destination, asset, relative_target))
                with source.open("rb") as incoming:
                    shutil.copyfileobj(incoming, out)
            with temporary.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("report fork asset changed during copy")
        for temporary, destination, asset, relative_target in staged:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                with destination.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != destination.stem:
                        raise ValueError("report fork destination asset hash mismatch")
            asset["local_ref"] = relative_target
            asset["content_hash"] = destination.stem
            asset["filename"] = destination.name
    finally:
        for temporary, *_ in staged:
            temporary.unlink(missing_ok=True)
