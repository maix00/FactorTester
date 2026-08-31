"""Git helpers for factor source workspaces."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.data_dir import get_feat_root
from tools.data.factor_workspace import storage as factor_workspace_storage
from tools.data.sqlite.factor_source_workspace_settings import (
    FIXED_DOWNLOAD_BRANCH,
    FIXED_UPLOAD_BRANCH,
    load_factor_source_workspace_settings,
    save_factor_source_workspace_settings,
)


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


def _git_dir(root: str) -> str | None:
    if not _git_binary_available():
        return None
    result = _run_git(root, "rev-parse", "--git-dir")
    if result.returncode != 0:
        return None
    git_dir = result.stdout.strip()
    if not git_dir:
        return None
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(root, git_dir)
    return git_dir


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


def _git_branch_exists(root: str, branch: str) -> bool:
    branch = str(branch or "").strip()
    if not branch or not _git_binary_available():
        return False
    result = _run_git(root, "show-ref", "--verify", f"refs/heads/{branch}")
    return result.returncode == 0


def _write_text_if_changed(path: str, content: str, *, executable: bool = False) -> bool:
    existing = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            existing = file.read()
    if existing == content:
        if executable and os.path.exists(path):
            current_mode = os.stat(path).st_mode
            if current_mode & 0o111:
                return False
        elif not executable:
            return False
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    if executable:
        os.chmod(path, 0o755)
    return True


def _install_git_autosync_hooks(root: str, username: str) -> list[str]:
    git_dir = _git_dir(root)
    if not git_dir:
        return []
    # Hooks outlive issue worktrees, so they must target the stable feat root.
    code_repo_root = get_feat_root()
    script_path = Path(code_repo_root) / "scripts" / "factor_workspace_autosync.py"
    if not script_path.exists():
        return []
    python_bin = sys.executable
    hook_template = """#!/bin/sh
set -eu
if [ "${{FACTOR_WORKSPACE_SKIP_AUTOSYNC:-}}" = "1" ]; then
    exit 0
fi
PYTHON={python}
SCRIPT={script}
USERNAME={username}
"$PYTHON" "$SCRIPT" --username "$USERNAME" --branch-mode auto >/dev/null 2>&1 || true
"""
    rendered = hook_template.format(
        python=repr(python_bin),
        script=repr(str(script_path)),
        username=repr(username),
    )
    installed: list[str] = []
    for hook_name in ("post-commit", "post-merge"):
        hook_path = os.path.join(git_dir, "hooks", hook_name)
        if _write_text_if_changed(hook_path, rendered, executable=True):
            installed.append(hook_path)
    return installed


def _materialize_workspace_branches(root: str, username: str) -> list[str]:
    if not _git_binary_available():
        return []
    auto_branch = FIXED_UPLOAD_BRANCH
    force_branch = FIXED_DOWNLOAD_BRANCH
    created: list[str] = []
    if _git_current_branch(root) is None:
        return created
    if not _git_branch_exists(root, auto_branch):
        if _run_git(root, "branch", auto_branch).returncode == 0:
            created.append(auto_branch)
    else:
        _run_git(root, "branch", "-f", auto_branch, "HEAD")
    if force_branch != auto_branch:
        if not _git_branch_exists(root, force_branch):
            if _run_git(root, "branch", force_branch).returncode == 0:
                created.append(force_branch)
        else:
            _run_git(root, "branch", "-f", force_branch, "HEAD")
    _git_checkout_branch(root, auto_branch)
    return created


def _ensure_git_workspace(root: str, username: str) -> dict[str, Any]:
    if not _git_binary_available():
        save_factor_source_workspace_settings(
            username,
            git_enabled=False,
            git_repo_root=None,
        )
        return {
            "git_enabled": False,
            "git_repo_root": "",
            "git_current_branch": "",
            "git_auto_sync_branch": FIXED_UPLOAD_BRANCH,
            "git_force_sync_branch": FIXED_DOWNLOAD_BRANCH,
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

    _ensure_git_commit_identity(root)
    repo_root = _git_repo_root(root) or root
    current_branch = _git_current_branch(root) or "main"
    branches = _git_branch_names(root)
    if current_branch not in branches:
        branches = [current_branch] + [branch for branch in branches if branch != current_branch]
    save_factor_source_workspace_settings(
        username,
        git_enabled=True,
        git_repo_root=repo_root,
    )
    _install_git_autosync_hooks(root, username)
    return {
        "git_enabled": True,
        "git_repo_root": repo_root,
        "git_current_branch": current_branch,
        "git_auto_sync_branch": FIXED_UPLOAD_BRANCH,
        "git_force_sync_branch": FIXED_DOWNLOAD_BRANCH,
        "git_branches": branches,
    }


def _ensure_git_commit_identity(root: str) -> None:
    """Configure a local identity only when Git has no usable identity."""
    defaults = {
        "user.name": "FactorTester Workspace",
        "user.email": "factor-workspace@localhost",
    }
    for key, value in defaults.items():
        configured = _run_git(root, "config", "--get", key)
        if configured.returncode == 0 and configured.stdout.strip():
            continue
        saved = _run_git(root, "config", "--local", key, value)
        if saved.returncode != 0:
            raise RuntimeError(f"cannot configure generated workspace {key}")


def _resolve_workspace_branch(username: str, branch_mode: str) -> str:
    if branch_mode == "force":
        return FIXED_DOWNLOAD_BRANCH
    if branch_mode == "auto":
        return FIXED_UPLOAD_BRANCH
    return FIXED_UPLOAD_BRANCH


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
        "auto_sync_branch": FIXED_UPLOAD_BRANCH,
        "force_sync_branch": FIXED_DOWNLOAD_BRANCH,
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
        "git_head": _git_head(root),
        "git_current_branch": _git_current_branch(root) or "",
        "git_auto_sync_branch": FIXED_UPLOAD_BRANCH,
        "git_force_sync_branch": FIXED_DOWNLOAD_BRANCH,
        "git_branches": branches,
    }


def _git_head(root: str) -> str:
    if not _git_binary_available() or not os.path.isdir(os.path.join(root, ".git")):
        return ""
    result = _run_git(root, "rev-parse", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""


def get_factor_workspace_autosync_branch(username: str) -> str:
    return FIXED_UPLOAD_BRANCH


def get_factor_workspace_current_branch(root: str) -> str:
    return _git_current_branch(root) or ""


def materialize_factor_workspace_branches(root: str, username: str) -> list[str]:
    return _materialize_workspace_branches(root, username)


def get_factor_workspace_download_branch(username: str) -> str:
    return FIXED_DOWNLOAD_BRANCH
