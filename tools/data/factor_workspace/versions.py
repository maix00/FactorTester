"""Read-only Git source history for factor-family provenance."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from tools.data.sqlite.factor_source_versions import (
    list_factor_source_version_snapshots,
    load_factor_source_version_snapshot,
)

from .storage import WORKSPACE_ROOTS_DIR, factor_source_root

_SOURCE_DIRS = {
    "custom": "custom_factors",
    "public": "public_factors",
}


@dataclass(frozen=True)
class _WorkspaceSource:
    root: str
    relative_path: str


def _safe_factor_id(factor_id: str) -> str:
    value = str(factor_id or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("factor family id is invalid")
    return value


def _source_path(source_kind: str, factor_id: str) -> str:
    directory = _SOURCE_DIRS.get(str(source_kind or "").strip())
    if not directory:
        raise ValueError("source kind must be custom or public")
    return f"{directory}/{_safe_factor_id(factor_id)}.py"


def _git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_text(root: str, *args: str) -> str:
    result = _git(root, *args)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_source(root: str, *args: str) -> str:
    result = _git(root, *args)
    if result.returncode != 0:
        return ""
    return result.stdout


def _source_hash(source_code: str) -> str:
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()


def _workspace_candidates(
    *, source_kind: str, owner_username: str, workspace_username: str = "",
) -> list[str]:
    values: list[str] = []
    for username in (workspace_username, owner_username):
        if not username:
            continue
        root = factor_source_root(username)
        if root not in values:
            values.append(root)
    if source_kind == "public" and os.path.isdir(WORKSPACE_ROOTS_DIR):
        for name in sorted(os.listdir(WORKSPACE_ROOTS_DIR)):
            root = os.path.join(WORKSPACE_ROOTS_DIR, name)
            if os.path.isdir(root) and root not in values:
                values.append(root)
    return values


def _find_workspace_source(
    *,
    source_kind: str,
    owner_username: str,
    factor_id: str,
    current_source: str,
    workspace_username: str = "",
) -> _WorkspaceSource | None:
    relative_path = _source_path(source_kind, factor_id)
    current_hash = _source_hash(current_source) if current_source else ""
    fallback: _WorkspaceSource | None = None
    for root in _workspace_candidates(
        source_kind=source_kind,
        owner_username=owner_username,
        workspace_username=workspace_username,
    ):
        if not os.path.isdir(os.path.join(root, ".git")):
            continue
        path = os.path.join(root, relative_path)
        if not os.path.isfile(path):
            continue
        candidate = _WorkspaceSource(root=root, relative_path=relative_path)
        if fallback is None:
            fallback = candidate
        if current_hash:
            source = _git_source(root, "show", f"HEAD:{relative_path}")
            if source and _source_hash(source) == current_hash:
                return candidate
    return fallback


def _branches_containing(root: str, commit: str) -> list[str]:
    output = _git_text(
        root, "branch", "--contains", commit, "--format=%(refname:short)",
    )
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def _version_row(
    *,
    root: str,
    relative_path: str,
    commit: str,
    committed_at: str,
    author: str,
    subject: str,
    source_code: str,
    current_hash: str,
) -> dict[str, Any] | None:
    if not source_code:
        return None
    source_hash = _source_hash(source_code)
    return {
        "commit": commit,
        "short_commit": commit[:12],
        "committed_at": int(committed_at or 0),
        "author": author,
        "subject": subject,
        "branches": _branches_containing(root, commit),
        "relative_path": relative_path,
        "source_hash": source_hash,
        "is_current": bool(current_hash and source_hash == current_hash),
    }


def list_factor_source_versions(
    *,
    source_kind: str,
    owner_username: str,
    factor_id: str,
    current_source: str,
    workspace_username: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """List only commits that changed the requested family source file."""
    source = _find_workspace_source(
        source_kind=source_kind,
        owner_username=owner_username,
        factor_id=factor_id,
        current_source=current_source,
        workspace_username=workspace_username,
    )
    current_hash = _source_hash(current_source) if current_source else ""
    bounded = min(200, max(1, int(limit)))
    snapshots = list_factor_source_version_snapshots(
        source_kind,
        owner_username,
        factor_id,
        current_hash=current_hash,
        limit=bounded,
    )
    if source is None:
        return {
            "available": bool(snapshots),
            "workspace": "server-db" if snapshots else "",
            "versions": snapshots,
            "current": {
                "commit": "",
                "short_commit": "",
                "committed_at": 0,
                "author": "",
                "subject": "当前源码",
                "branches": [],
                "relative_path": _source_path(source_kind, factor_id),
                "source_hash": current_hash,
                "is_current": True,
            },
            "relative_path": _source_path(source_kind, factor_id),
        }

    rows = _git_text(
        source.root,
        "log", "--all", "--follow", f"--max-count={bounded * 3}",
        "--format=%H%x1f%ct%x1f%an%x1f%s", "--", source.relative_path,
    )
    versions: list[dict[str, Any]] = []
    seen_blobs: set[str] = set()
    for line in rows.splitlines():
        commit, timestamp, author, subject = (
            line.split("\x1f", 3) + ["", "", "", ""]
        )[:4]
        commit = commit.strip()
        if not commit:
            continue
        source_code = _git_source(
            source.root, "show", f"{commit}:{source.relative_path}",
        )
        if not source_code:
            continue
        source_hash = _source_hash(source_code)
        if source_hash in seen_blobs:
            continue
        seen_blobs.add(source_hash)
        version = _version_row(
            root=source.root,
            relative_path=source.relative_path,
            commit=commit,
            committed_at=timestamp,
            author=author,
            subject=subject,
            source_code=source_code,
            current_hash=current_hash,
        )
        if version is not None:
            versions.append(version)
        if len(versions) >= bounded:
            break

    head = _git_text(source.root, "rev-parse", "HEAD")
    current = next((item for item in versions if item["is_current"]), None)
    if current is None:
        current = {
            "commit": head,
            "short_commit": head[:12],
            "committed_at": 0,
            "author": "",
            "subject": "当前源码",
            "branches": [_git_text(source.root, "branch", "--show-current")],
            "relative_path": source.relative_path,
            "source_hash": current_hash,
            "is_current": True,
            "uncommitted": True,
        }
    merged: list[dict[str, Any]] = []
    seen_commits: set[str] = set()
    for item in [*versions, *snapshots]:
        commit = str(item.get("commit") or "")
        if not commit or commit in seen_commits:
            continue
        seen_commits.add(commit)
        merged.append(item)
        if len(merged) >= bounded:
            break
    return {
        "available": True,
        "workspace": "server",
        "relative_path": source.relative_path,
        "current": current,
        "versions": merged,
    }


def load_factor_source_version(
    *,
    source_kind: str,
    owner_username: str,
    factor_id: str,
    current_source: str,
    commit: str,
    workspace_username: str = "",
) -> dict[str, Any]:
    """Load one exact source revision without changing the checked-out branch."""
    if commit in {"", "current", "latest"}:
        return {
            "commit": "",
            "source_code": current_source,
            "source_hash": _source_hash(current_source),
            "is_current": True,
        }
    snapshot = load_factor_source_version_snapshot(
        source_kind,
        owner_username,
        factor_id,
        commit,
    )
    if snapshot is not None:
        snapshot["is_current"] = bool(
            current_source
            and _source_hash(snapshot.get("source_code") or "")
            == _source_hash(current_source)
        )
        return snapshot

    source = _find_workspace_source(
        source_kind=source_kind,
        owner_username=owner_username,
        factor_id=factor_id,
        current_source=current_source,
        workspace_username=workspace_username,
    )
    if source is None:
        raise FileNotFoundError("factor source Git workspace is unavailable")
    resolved = _git_text(source.root, "rev-parse", f"{commit}^{{commit}}")
    if not resolved:
        raise FileNotFoundError("factor source Git version is unavailable")
    source_code = _git_source(
        source.root, "show", f"{resolved}:{source.relative_path}",
    )
    if not source_code:
        raise FileNotFoundError("factor source is absent at the selected Git version")
    return {
        "commit": resolved,
        "source_code": source_code,
        "source_hash": _source_hash(source_code),
        "is_current": bool(
            current_source and _source_hash(source_code) == _source_hash(current_source)
        ),
        "relative_path": source.relative_path,
        "branches": _branches_containing(source.root, resolved),
    }


__all__ = ["list_factor_source_versions", "load_factor_source_version"]
