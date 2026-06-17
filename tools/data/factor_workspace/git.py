"""Git helpers for factor source workspaces."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from tools.data.sqlite.factor_source_workspace_settings import (
    load_factor_source_workspace_settings,
    save_factor_source_workspace_settings,
)
from tools.data.factor_workspace import storage as factor_workspace_storage


def _workspace_root(username: str) -> str:
    return factor_workspace_storage.factor_source_root(username)


def _git_binary_available() -> bool:
    return shutil.which("git") is not None


def _run_git(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", root, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_repo_root(root: str) -> str | None:
    if not _git_binary_available():
        return None
    result = _run_git(root, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_current_branch(root: str) -> str | None:
    if not _git_binary_available():
        return None
    result = _run_git(root, "branch", "--show-current")
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def _git_branch_names(root: str) -> list[str]:
    if not _git_binary_available():
        return []
    result = _run_git(root, "branch", "--format=%(refname:short)")
    if result.returncode != 0:
        return []
    branches = [line.strip().lstrip("* ").strip() for line in result.stdout.splitlines()]
    return [branch for branch in branches if branch]


def _git_checkout_branch(root: str, branch: str) -> bool:
    branch = str(branch or "").strip()
    if not branch or not _git_binary_available() or not os.path.isdir(os.path.join(root, ".git")):
        return False
    current_branch = _git_current_branch(root)
    if current_branch == branch:
        return False
    result = _run_git(root, "checkout", "-B", branch)
    if result.returncode != 0:
        return False
    return True


def _ensure_git_workspace(root: str, username: str) -> dict[str, Any]:
    if not _git_binary_available():
        save_factor_source_workspace_settings(
            username,
            git_enabled=False,
            git_repo_root=None,
            auto_sync_branch="",
            force_sync_branch="",
        )
        return {
            "git_enabled": False,
            "git_repo_root": "",
            "git_current_branch": "",
            "git_auto_sync_branch": "",
            "git_force_sync_branch": "",
            "git_branches": [],
        }

    git_dir = os.path.join(root, ".git")
    if not os.path.exists(git_dir):
        init = subprocess.run(
            ["git", "init", "-b", "main", root],
            check=False,
            capture_output=True,
            text=True,
        )
        if init.returncode != 0:
            subprocess.run(["git", "init", root], check=False, capture_output=True, text=True)
            subprocess.run(["git", "-C", root, "checkout", "-B", "main"], check=False, capture_output=True, text=True)

    repo_root = _git_repo_root(root) or root
    current_branch = _git_current_branch(root) or "main"
    branches = _git_branch_names(root)
    if current_branch not in branches:
        branches = [current_branch] + [branch for branch in branches if branch != current_branch]
    existing = load_factor_source_workspace_settings(username) or {}
    auto_branch = str(existing.get("auto_sync_branch") or current_branch or "main")
    force_branch = str(existing.get("force_sync_branch") or auto_branch)
    save_factor_source_workspace_settings(
        username,
        git_enabled=True,
        git_repo_root=repo_root,
        auto_sync_branch=auto_branch,
        force_sync_branch=force_branch,
    )
    return {
        "git_enabled": True,
        "git_repo_root": repo_root,
        "git_current_branch": current_branch,
        "git_auto_sync_branch": auto_branch,
        "git_force_sync_branch": force_branch,
        "git_branches": branches,
    }


def _resolve_workspace_branch(username: str, branch_mode: str) -> str:
    settings = load_factor_source_workspace_settings(username) or {}
    auto_branch = str(settings.get("auto_sync_branch") or "").strip()
    force_branch = str(settings.get("force_sync_branch") or "").strip()
    if branch_mode == "force" and force_branch:
        return force_branch
    if auto_branch:
        return auto_branch
    return force_branch


def _apply_workspace_git_branch(root: str, username: str, branch_mode: str) -> str:
    branch = _resolve_workspace_branch(username, branch_mode)
    if branch:
        _git_checkout_branch(root, branch)
    return branch


def _git_commit_all(root: str, message: str) -> str | None:
    if not _git_binary_available() or not os.path.isdir(os.path.join(root, ".git")):
        return None
    status = _run_git(root, "status", "--porcelain")
    if status.returncode != 0:
        return None
    if not status.stdout.strip():
        return None
    add = _run_git(root, "add", "-A")
    if add.returncode != 0:
        return None
    commit = _run_git(root, "commit", "-m", message)
    if commit.returncode != 0:
        return None
    rev = _run_git(root, "rev-parse", "--short", "HEAD")
    if rev.returncode != 0:
        return None
    return rev.stdout.strip() or None


def _load_workspace_config(username: str) -> dict[str, Any]:
    settings = load_factor_source_workspace_settings(username) or {}
    return {
        "git_enabled": bool(settings.get("git_enabled")),
        "git_repo_root": str(settings.get("git_repo_root") or ""),
        "auto_sync_branch": str(settings.get("auto_sync_branch") or ""),
        "force_sync_branch": str(settings.get("force_sync_branch") or ""),
    }


def get_factor_workspace_git_state(username: str) -> dict[str, Any]:
    root = _workspace_root(username)
    settings = load_factor_source_workspace_settings(username) or {}
    repo_root = str(settings.get("git_repo_root") or "")
    branches = _git_branch_names(root) if os.path.isdir(root) else []
    return {
        "workspace_root": root,
        "git_enabled": bool(settings.get("git_enabled")),
        "git_repo_root": repo_root,
        "git_current_branch": _git_current_branch(root) or "",
        "git_auto_sync_branch": str(settings.get("auto_sync_branch") or ""),
        "git_force_sync_branch": str(settings.get("force_sync_branch") or ""),
        "git_branches": branches,
    }
