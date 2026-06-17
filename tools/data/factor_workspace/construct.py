"""Workspace construction entrypoints."""

from __future__ import annotations

from typing import Any

from .git import _git_commit_all
from .pre import _workspace_root
from .sync import sync_database_to_workspace


def build_factor_workspace(username: str) -> dict[str, Any]:
    result = sync_database_to_workspace(username, branch_mode="force", clear_existing=True)
    git_info = result.get("git") or {}
    if git_info.get("git_enabled"):
        root = result.get("workspace_root") or _workspace_root(username)
        commit_sha = _git_commit_all(str(root), "chore: rebuild factor workspace")
        if commit_sha:
            result["git_commit_sha"] = commit_sha
    return result

