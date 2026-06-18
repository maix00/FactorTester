from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _bootstrap_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _git_head(workspace_root: str) -> str:
    result = subprocess.run(
        ["git", "-C", workspace_root, "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _autosync_marker_path(workspace_root: str) -> Path:
    return Path(workspace_root) / ".factor_workspace" / "last_autosync_head"


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-sync factor workspace to database after git updates.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--branch-mode", default="auto")
    args = parser.parse_args()

    _bootstrap_repo()

    from tools.data.account_manage import get_account, is_super_admin_account
    from tools.data.factor_workspace.git import (
        _git_checkout_branch,
        get_factor_workspace_autosync_branch,
        get_factor_workspace_current_branch,
        get_factor_workspace_download_branch,
    )
    from tools.data.factor_workspace.sync import push_factor_workspace, sync_factor_workspace

    result = push_factor_workspace(
        args.username,
        allow_public_write=is_super_admin_account(get_account(args.username)),
        branch_mode=args.branch_mode,
    )
    if result.get("skipped"):
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    upload_branch = get_factor_workspace_autosync_branch(args.username) or "upload"
    download_branch = get_factor_workspace_download_branch(args.username) or "download"
    workspace_root = str(result.get("workspace_root") or "").strip()
    if not workspace_root:
        print(json.dumps({**result, "error": "未能解析工作区根目录"}, ensure_ascii=False, sort_keys=True))
        return 1
    current_head = _git_head(workspace_root)
    marker_path = _autosync_marker_path(workspace_root)
    if current_head and marker_path.exists():
        previous_head = marker_path.read_text(encoding="utf-8").strip()
        if previous_head == current_head:
            result["skipped"] = True
            result["skip_reason"] = "当前提交已经完成过自动同步"
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
    previous_skip = os.environ.get("FACTOR_WORKSPACE_SKIP_AUTOSYNC")
    os.environ["FACTOR_WORKSPACE_SKIP_AUTOSYNC"] = "1"
    try:
        sync_result = sync_factor_workspace(args.username, branch_mode="force")
        result["download_sync"] = sync_result

        workspace_root = str(sync_result.get("workspace_root") or workspace_root)
        current_branch = get_factor_workspace_current_branch(workspace_root)
        if current_branch != upload_branch:
            _git_checkout_branch(workspace_root, upload_branch)

        merge = subprocess.run(
            ["git", "-C", workspace_root, "merge", "--no-ff", "--no-commit", "--no-edit", download_branch],
            check=False,
            capture_output=True,
            text=True,
        )
        if merge.returncode == 0:
            commit = subprocess.run(
                ["git", "-C", workspace_root, "commit", "--no-verify", "-m", "chore: sync download snapshot"],
                check=False,
                capture_output=True,
                text=True,
            )
            result["git_merge_commit_returncode"] = commit.returncode
            if commit.returncode != 0:
                if "nothing to commit" in (commit.stdout or "").lower():
                    result["git_merge_commit_returncode"] = 0
                else:
                    result["git_merge_commit_stdout"] = commit.stdout
                    result["git_merge_commit_stderr"] = commit.stderr
                    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                    return commit.returncode
        final_head = _git_head(workspace_root)
        if final_head:
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(final_head + "\n", encoding="utf-8")
    finally:
        if previous_skip is None:
            os.environ.pop("FACTOR_WORKSPACE_SKIP_AUTOSYNC", None)
        else:
            os.environ["FACTOR_WORKSPACE_SKIP_AUTOSYNC"] = previous_skip

    result["git_merge_returncode"] = merge.returncode
    if merge.returncode != 0:
        result["git_merge_stdout"] = merge.stdout
        result["git_merge_stderr"] = merge.stderr
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return merge.returncode

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
