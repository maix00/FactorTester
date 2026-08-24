"""Database/workspace synchronization for factor sources."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from tools.data.sqlite.factor_source_store import list_factor_sources

from .git import get_factor_workspace_autosync_branch
from .repository import FactorWorkspaceRepository
from . import storage as factor_workspace_storage
from .construct import (
    _clear_workspace_generated,
    _ensure_workspace_layout,
    _remove_missing_files,
    _sync_tools_index,
    _sync_tools_sdk,
    _sync_vscode_settings,
    _workspace_custom_dir,
    _workspace_public_dir,
    _workspace_root,
    _write_json,
    _write_text_if_changed,
)


def _assert_workspace_owner(root: str, username: str) -> None:
    """Refuse any sync against a non-empty workspace owned elsewhere."""
    if not os.path.isdir(root) or not os.listdir(root):
        return

    manifest_path = os.path.join(root, ".factor_workspace", "manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError):
        manifest = {}

    owner = str(manifest.get("username") or "").strip() if isinstance(manifest, dict) else ""
    if not owner:
        raise PermissionError(
            f"拒绝清空非空目录 {root!r}：没有有效的 Factor Workspace 所有权标记"
        )
    if owner != username:
        raise PermissionError(
            f"拒绝清空 Factor Workspace {root!r}：所有者为 {owner!r}，"
            f"当前 profile 为 {username!r}"
        )


def sync_database_to_workspace(username: str, branch_mode: str = "auto", clear_existing: bool = False) -> dict[str, Any]:
    root = _workspace_root(username)
    factor_workspace_storage.assert_canonical_factor_workspace_root(root)
    _assert_workspace_owner(root, username)
    _ensure_workspace_layout(root)
    repository = FactorWorkspaceRepository(username)
    git_info = repository.ensure()
    selected_branch = repository.checkout(branch_mode)

    cleared_files: list[str] = []
    if clear_existing:
        cleared_files = _clear_workspace_generated(root)

    custom_count = 0
    public_count = 0
    touched_files: list[str] = []
    expected_custom_files: set[str] = set()
    expected_public_files: set[str] = set()

    for record in list_factor_sources("custom"):
        owner_username = str(record.get("owner_username") or "")
        factor_id = str(record.get("factor_id") or "")
        source_code = str(record.get("source_code") or "")
        if not owner_username or not factor_id or not source_code:
            continue
        if owner_username != username:
            continue
        expected_custom_files.add(f"{factor_id}.py")
        local_path = factor_workspace_storage.factor_path(username, factor_id)
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        custom_count += 1

    for record in list_factor_sources("public"):
        factor_id = str(record.get("factor_id") or "")
        source_code = str(record.get("source_code") or "")
        if not factor_id or not source_code:
            continue
        expected_public_files.add(f"{factor_id}.py")
        local_path = os.path.join(_workspace_public_dir(root), f"{factor_id}.py")
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        public_count += 1

    removed_files: list[str] = []
    removed_files.extend(_remove_missing_files(_workspace_custom_dir(root), expected_custom_files))
    removed_files.extend(_remove_missing_files(_workspace_public_dir(root), expected_public_files))

    tools_index_changed = _sync_tools_index(root)
    tools_sdk_changed = _sync_tools_sdk(root)
    vscode_settings_changed = _sync_vscode_settings(root)

    manifest = {
        "workspace_root": root,
        "username": username,
        "custom_factor_dir": factor_workspace_storage.custom_factor_dir(username),
        "public_factor_dir": _workspace_public_dir(root),
        "git": repository.state() if git_info.get("git_enabled") else git_info,
        "git_selected_branch": selected_branch,
        "cleared_files": cleared_files,
        "custom_factor_count": custom_count,
        "public_factor_count": public_count,
        "touched_files": touched_files,
        "removed_files": removed_files,
    }
    manifest_changed = _write_json(os.path.join(root, ".factor_workspace", "manifest.json"), manifest)

    return {
        "workspace_root": root,
        "custom_factor_count": custom_count,
        "public_factor_count": public_count,
        "git": repository.state() if git_info.get("git_enabled") else git_info,
        "git_selected_branch": selected_branch,
        "cleared_files": cleared_files,
        "touched_files": touched_files,
        "removed_files": removed_files,
        "tools_index_changed": tools_index_changed,
        "tools_sdk_changed": tools_sdk_changed,
        "vscode_settings_changed": vscode_settings_changed,
        "manifest_changed": manifest_changed,
    }


def sync_factor_workspace(username: str, branch_mode: str = "force") -> dict[str, Any]:
    result = sync_database_to_workspace(username, branch_mode=branch_mode)
    if branch_mode == "force":
        root = str(result.get("workspace_root") or _workspace_root(username))
        commit_sha = FactorWorkspaceRepository(username).commit_generated(
            "chore: sync database to workspace"
        )
        if commit_sha:
            result["git_commit_sha"] = commit_sha
    return result


def sync_workspace_to_database(username: str, branch_mode: str = "auto") -> dict[str, Any]:
    root = _workspace_root(username)
    factor_workspace_storage.assert_canonical_factor_workspace_root(root)
    _assert_workspace_owner(root, username)
    _ensure_workspace_layout(root)
    repository = FactorWorkspaceRepository(username)
    repository.ensure()
    selected_branch = repository.checkout(branch_mode)

    custom_dir = _workspace_custom_dir(root)
    updated_custom = 0
    updated_public = 0
    public_factor_changes: list[dict[str, object]] = []

    if os.path.isdir(custom_dir):
        for filename in sorted(os.listdir(custom_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            source = factor_workspace_storage.load_factor_source(username, factor_id)
            file_path = os.path.join(custom_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if source != source_code:
                factor_workspace_storage.save_factor_source(username, factor_id, source_code)
                updated_custom += 1

    public_dir = _workspace_public_dir(root)
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if factor_workspace_storage.load_public_factor_source(factor_id) != source_code:
                factor_workspace_storage.save_public_factor_source(factor_id, source_code)
                updated_public += 1
                normalized = factor_workspace_storage.load_public_factor_source(
                    factor_id,
                ) or ""
                raw = normalized.encode("utf-8")
                public_factor_changes.append({
                    "factor_id": factor_id,
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_bytes": len(raw),
                })

    return {
        "workspace_root": root,
        "git_selected_branch": selected_branch,
        "updated_custom_count": updated_custom,
        "updated_public_count": updated_public,
        "public_factor_changes": public_factor_changes,
    }


def push_factor_workspace(username: str, allow_public_write: bool = False, branch_mode: str = "auto") -> dict[str, Any]:
    root = _workspace_root(username)
    factor_workspace_storage.assert_canonical_factor_workspace_root(root)
    _assert_workspace_owner(root, username)
    _ensure_workspace_layout(root)
    repository = FactorWorkspaceRepository(username)
    repository.ensure()
    current_branch = repository.current_branch()
    auto_branch = get_factor_workspace_autosync_branch(username)
    if branch_mode == "auto" and auto_branch and current_branch != auto_branch:
        return {
            "workspace_root": root,
            "git_selected_branch": current_branch,
            "skipped": True,
            "skip_reason": f"当前分支 {current_branch} 不是自动同步分支 {auto_branch}",
            "updated_custom_count": 0,
            "updated_public_count": 0,
        }
    selected_branch = repository.checkout(branch_mode)

    public_dir = _workspace_public_dir(root)
    changed_public_files: list[str] = []
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if factor_workspace_storage.load_public_factor_source(factor_id) != source_code:
                changed_public_files.append(file_path)

    if changed_public_files and not allow_public_write:
        rel = [os.path.relpath(path, root) for path in changed_public_files]
        raise PermissionError(f"只有超级管理员可以同步公共因子到数据库：{rel}")

    result = sync_workspace_to_database(username, branch_mode=branch_mode)
    result["git_selected_branch"] = selected_branch or result.get("git_selected_branch", "")
    return result
