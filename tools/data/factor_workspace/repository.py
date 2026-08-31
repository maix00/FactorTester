"""Repository boundary for a user's factor workspace Git lifecycle."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from tools.data.sqlite.factor_source_workspace_settings import (
    FIXED_DOWNLOAD_BRANCH,
    FIXED_UPLOAD_BRANCH,
)

from . import git, storage


@dataclass(frozen=True)
class FactorWorkspaceRepository:
    username: str

    @property
    def root(self) -> str:
        return storage.factor_source_root(self.username)

    def ensure(self) -> dict[str, Any]:
        return git._ensure_git_workspace(self.root, self.username)

    def checkout(self, branch_mode: str) -> str:
        return git._apply_workspace_git_branch(self.root, self.username, branch_mode)

    def commit(self, message: str) -> str | None:
        return git._git_commit_all(self.root, message)

    def commit_generated(self, message: str) -> str | None:
        """Commit generated files without recursively invoking user autosync."""
        previous = os.environ.get("FACTOR_WORKSPACE_SKIP_AUTOSYNC")
        os.environ["FACTOR_WORKSPACE_SKIP_AUTOSYNC"] = "1"
        try:
            return self.commit(message)
        finally:
            if previous is None:
                os.environ.pop("FACTOR_WORKSPACE_SKIP_AUTOSYNC", None)
            else:
                os.environ["FACTOR_WORKSPACE_SKIP_AUTOSYNC"] = previous

    def materialize_branches(self) -> list[str]:
        return git._materialize_workspace_branches(self.root, self.username)

    def state(self) -> dict[str, Any]:
        return git.get_factor_workspace_git_state(self.username)

    def current_branch(self) -> str:
        return git.get_factor_workspace_current_branch(self.root)

    def head(self) -> str:
        result = git._run_git(self.root, "rev-parse", "HEAD")
        return result.stdout.strip() if result.returncode == 0 else ""

    def merge_download_snapshot(self) -> dict[str, Any]:
        if self.current_branch() != FIXED_UPLOAD_BRANCH:
            git._git_checkout_branch(self.root, FIXED_UPLOAD_BRANCH)
        merge = git._run_git(
            self.root,
            "merge",
            "--no-ff",
            "--no-commit",
            "--no-edit",
            FIXED_DOWNLOAD_BRANCH,
        )
        result: dict[str, Any] = {
            "git_merge_returncode": merge.returncode,
            "git_merge_stdout": merge.stdout,
            "git_merge_stderr": merge.stderr,
        }
        if merge.returncode != 0:
            return result
        commit = git._run_git(
            self.root,
            "commit",
            "--no-verify",
            "-m",
            "chore: sync download snapshot",
        )
        nothing_to_commit = "nothing to commit" in f"{commit.stdout}\n{commit.stderr}".lower()
        result["git_merge_commit_returncode"] = 0 if nothing_to_commit else commit.returncode
        result["git_merge_commit_stdout"] = commit.stdout
        result["git_merge_commit_stderr"] = commit.stderr
        return result
