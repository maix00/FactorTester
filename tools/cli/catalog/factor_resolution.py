"""Resolve local factor settings to immutable source references."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.references.factor_git import (
    freeze_factor_reference_at_revision,
)
from tools.cli.release.user_layout import default_user_factor_library


def resolve_local_factor_reference(
    *,
    client_root: Path,
    owner_ref: str,
    alias: str,
    revision: str = "HEAD",
) -> dict[str, Any]:
    """Resolve owner, commit and alias to one frozen concrete factor ref."""
    owner_ref = str(owner_ref or "").strip()
    alias = str(alias or "").strip()
    if not owner_ref:
        raise ValueError("factor owner_ref is required")
    if not alias:
        raise ValueError("factor alias is required")
    repository, scope = _owner_repository(
        client_root=client_root, owner_ref=owner_ref,
    )
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    family = alias.split("|", 1)[0].strip()
    if not family:
        raise ValueError("factor alias has no family")
    relative_path = _factor_source_path(
        repository=repository, commit=commit, family=family,
    )
    frozen = freeze_factor_reference_at_revision(
        object_kind="factor",
        scope=scope,
        repository=repository,
        relative_path=relative_path,
        identity=alias,
        revision=commit,
    )
    family_frozen = freeze_factor_reference_at_revision(
        object_kind="factor-family",
        scope=scope,
        repository=repository,
        relative_path=relative_path,
        identity=family,
        revision=commit,
    )
    return {
        "schema_version": 1,
        "owner_ref": owner_ref,
        "repository": str(repository),
        "scope": scope,
        "family": family,
        "alias": alias,
        "git_commit": frozen["revision"],
        "git_blob": frozen["blob_hash"],
        "relative_path": frozen["relative_path"],
        "factor_ref": frozen["target_ref"],
        "family_ref": family_frozen["target_ref"],
    }


def _owner_repository(*, client_root: Path, owner_ref: str) -> tuple[Path, str]:
    if owner_ref.startswith("profile:"):
        profile_id = owner_ref.removeprefix("profile:")
        if not profile_id or ":" in profile_id:
            raise ValueError("profile factor owner_ref is invalid")
        profile = LocalProfileStore(client_root).load(profile_id)
        binding = profile.get("factor_workspace_binding") or {}
        worktree = str(binding.get("worktree_path") or "").strip()
        if not worktree:
            raise ValueError("Profile has no registered factor worktree")
        repository = Path(worktree).expanduser().resolve()
        scope = f"profile-{profile_id}"
    elif owner_ref.startswith(("user:", "principal:")):
        principal = owner_ref.split(":", 1)[1]
        if not principal or ":" in principal:
            raise ValueError("personal factor owner_ref is invalid")
        repository = default_user_factor_library(principal).resolve()
        scope = "personal"
    else:
        raise ValueError(
            "factor owner_ref must be profile:<id>, user:<id>, or principal:<id>"
        )
    if not repository.is_dir():
        raise ValueError(f"factor repository is unavailable: {repository}")
    _git(repository, "rev-parse", "--is-inside-work-tree")
    return repository, scope


def _factor_source_path(
    *, repository: Path, commit: str, family: str,
) -> str:
    paths = [
        line.strip()
        for line in _git(
            repository, "ls-tree", "-r", "--name-only", commit,
        ).splitlines()
        if line.strip().endswith(".py")
    ]
    exact = [path for path in paths if Path(path).stem == family]
    preferred = [
        path for path in exact
        if path in {f"custom_factors/{family}.py", f"Factors/{family}.py"}
    ]
    candidates = preferred or exact
    if not candidates:
        raise ValueError(
            f"selected Git revision has no source for factor family {family!r}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"selected Git revision has ambiguous sources for factor family {family!r}"
        )
    return candidates[0]


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        message = result.stderr.strip() or "Git object is unavailable"
        raise ValueError(f"factor resolution failed: {message}")
    return result.stdout.strip()
