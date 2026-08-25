"""Resolve local factor settings to immutable source references."""

from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.references.workspace_factor_reference import (
    freeze_factor_reference_at_revision,
)
from tools.cli.release.user_layout import default_user_factor_library
from .factor_engine import describe_factor_family, instantiate_factor_family


def list_local_factor_revisions(
    *, client_root: Path, owner_ref: str, limit: int = 50,
) -> list[dict[str, Any]]:
    """List bounded Git revisions for one registered factor owner."""
    repository, _scope = _owner_repository(
        client_root=client_root, owner_ref=owner_ref,
    )
    bounded = min(200, max(1, int(limit)))
    rows = _git(
        repository,
        "log",
        f"--max-count={bounded}",
        "--format=%H%x1f%ct%x1f%s",
    ).splitlines()
    result = []
    for row in rows:
        commit, timestamp, subject = (row.split("\x1f", 2) + ["", ""])[:3]
        if not commit:
            continue
        result.append({
            "owner_ref": owner_ref,
            "git_commit": commit,
            "committed_at": int(timestamp or 0),
            "subject": subject,
        })
    return result


def list_local_factor_families(
    *, client_root: Path, owner_ref: str, revision: str,
) -> list[dict[str, Any]]:
    """List family source identities at an exact commit without importing."""
    repository, _scope = _owner_repository(
        client_root=client_root, owner_ref=owner_ref,
    )
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    result = [
        {
            "owner_ref": owner_ref,
            "git_commit": commit,
            "relative_path": relative_path,
            "family": Path(relative_path).stem,
        }
        for relative_path in _factor_python_paths(
            repository=repository, commit=commit,
        )
    ]
    result.sort(key=lambda item: item["family"])
    return result


def describe_local_factor_family(
    *, client_root: Path, owner_ref: str, revision: str, family: str,
) -> dict[str, Any]:
    """Load parameter metadata for one selected, frozen family only."""
    repository, scope = _owner_repository(
        client_root=client_root, owner_ref=owner_ref,
    )
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    relative_path = _factor_source_path(
        repository=repository, commit=commit, family=family,
    )
    blob = _git(repository, "rev-parse", f"{commit}:{relative_path}")
    metadata = _engine_metadata(
        repository=repository,
        commit=commit,
        relative_path=relative_path,
        family=family,
        blob_hash=blob,
    )
    if str(metadata.pop("family", "")) != family:
        raise ValueError(
            f"selected Git revision cannot load factor family {family!r}"
        )
    frozen = freeze_factor_reference_at_revision(
        object_kind="factor-family",
        scope=scope,
        repository=repository,
        relative_path=relative_path,
        identity=family,
        revision=commit,
    )
    return {
        **metadata,
        **frozen["record"],
        "workspace_provenance": frozen["workspace_provenance"],
    }


def instantiate_local_factor(
    *,
    client_root: Path,
    owner_ref: str,
    revision: str,
    family: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Instantiate one candidate from a family frozen at a selected commit."""
    repository, _scope = _owner_repository(
        client_root=client_root, owner_ref=owner_ref,
    )
    commit = _git(repository, "rev-parse", f"{revision}^{{commit}}")
    relative_path = _factor_source_path(
        repository=repository, commit=commit, family=family,
    )
    blob = _git(repository, "rev-parse", f"{commit}:{relative_path}")
    candidate = _engine_candidate(
        repository=repository,
        commit=commit,
        relative_path=relative_path,
        family=family,
        blob_hash=blob,
        params=params,
    )
    if str(candidate.get("family") or "") != family:
        raise ValueError(
            f"selected source resolves family {candidate.get('family', '')!r}, "
            f"not {family!r}"
        )
    alias = str(candidate.get("alias") or "").strip()
    if not alias:
        raise ValueError("factor engine helper omitted the candidate alias")
    frozen = resolve_local_factor_reference(
        client_root=client_root,
        owner_ref=owner_ref,
        alias=alias,
        revision=commit,
    )
    if frozen["identity"]["params"] != (candidate.get("params") or {}):
        raise ValueError("factor parameter normalization changed during freeze")
    return frozen


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
    return {
        **frozen["record"],
        "repository": str(repository),
        "scope": scope,
        "workspace_provenance": frozen["workspace_provenance"],
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
    paths = _factor_python_paths(repository=repository, commit=commit)
    exact = [path for path in paths if Path(path).stem == family]
    preferred = [
        path for path in exact
        if path in {
            f"custom_factors/{family}.py",
            f"public_factors/{family}.py",
        }
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


def _factor_python_paths(*, repository: Path, commit: str) -> list[str]:
    return [
        line.strip()
        for line in _git(
            repository, "ls-tree", "-r", "--name-only", commit,
        ).splitlines()
        if line.strip().endswith(".py")
        and not Path(line.strip()).name.startswith("__")
        and Path(line.strip()).parts[0] in {
            "custom_factors", "public_factors",
        }
    ]


def _engine_metadata(
    *,
    repository: Path,
    commit: str,
    relative_path: str,
    family: str,
    blob_hash: str,
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="factortester-catalog-family-") as directory:
        source = Path(directory) / Path(relative_path).name
        source.write_text(
            _git(repository, "show", f"{commit}:{relative_path}"),
            encoding="utf-8",
        )
        return describe_factor_family(
            source_file=source, family=family, blob_hash=blob_hash,
        )


def _engine_candidate(
    *,
    repository: Path,
    commit: str,
    relative_path: str,
    family: str,
    blob_hash: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="factortester-catalog-factor-") as directory:
        source = Path(directory) / Path(relative_path).name
        source.write_text(
            _git(repository, "show", f"{commit}:{relative_path}"),
            encoding="utf-8",
        )
        return instantiate_factor_family(
            source_file=source,
            family=family,
            blob_hash=blob_hash,
            params=params,
        )


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        message = result.stderr.strip() or "Git object is unavailable"
        raise ValueError(f"factor resolution failed: {message}")
    return result.stdout.strip()
