"""Compatibility wrapper for factor workspace services."""

from __future__ import annotations

from tools.data.factor_workspace.construct import build_factor_workspace
from tools.data.factor_workspace.git import (
    get_factor_workspace_git_state,
    run_factor_workspace_git_action,
)
from tools.data.factor_workspace.repository import FactorWorkspaceRepository
from tools.data.factor_workspace.storage import existing_factor_workspace_root
from tools.data.sqlite.factor_source_workspace_settings import (
    load_factor_source_workspace_settings,
)
from tools.data.factor_workspace.sync import (
    push_factor_workspace,
    sync_database_to_workspace,
    sync_factor_workspace,
    sync_workspace_to_database,
)


def commit_factor_source_change(username: str, message: str) -> dict:
    """Optionally mirror a saved source into an explicitly configured Git workspace.

    The SQLite source registry is authoritative.  A Web save must remain
    successful when the user has no server workspace or has disabled Git; in
    those cases the returned commit is empty and the caller records a server
    source revision instead.
    """
    root = existing_factor_workspace_root(username)
    settings = load_factor_source_workspace_settings(username) or {}
    if not root or not bool(settings.get("git_enabled")):
        return {
            "git_commit_sha": "",
            "workspace_root": root or "",
            "git": {"git_enabled": False, "git_repo_root": ""},
        }
    result = sync_database_to_workspace(
        username, branch_mode="auto", clear_existing=False,
    )
    git_state = result.get("git") or {}
    if not git_state.get("git_enabled"):
        raise RuntimeError("Factor Workspace Git 未启用，无法记录源码提交")
    repository = FactorWorkspaceRepository(username)
    commit_sha = repository.commit_generated(message) or repository.head()
    if not commit_sha:
        raise RuntimeError("源码已保存，但没有生成 Git 提交记录")
    result["git_commit_sha"] = commit_sha
    result["git"] = repository.state()
    result["git_selected_branch"] = result["git"].get("git_current_branch", "")
    return result

__all__ = [
    "build_factor_workspace",
    "commit_factor_source_change",
    "get_factor_workspace_git_state",
    "push_factor_workspace",
    "run_factor_workspace_git_action",
    "sync_database_to_workspace",
    "sync_factor_workspace",
    "sync_workspace_to_database",
]
