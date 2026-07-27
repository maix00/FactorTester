"""Independent strategy-source repository and Profile worktree contract."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess
from typing import Any

from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json
from .user_layout import default_user_strategy_library


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(path: Path) -> Path:
    value = Path(_git(path.resolve(), "rev-parse", "--show-toplevel"))
    return value.resolve()


def _owner(repo: Path) -> str:
    value = read_json(repo / ".strategy_workspace" / "manifest.json")
    if not isinstance(value, dict) or value.get("kind") != "strategy-source":
        raise ValueError("strategy repository manifest is missing")
    return str(value.get("owner_ref") or "")


class CanonicalStrategyRepoStore:
    """Persist the registered personal strategy repository identity."""

    def __init__(self, client_root: Path) -> None:
        self.root = validate_client_root(client_root)
        self.path = self.root / "settings" / "strategy-workspace.json"

    def register(self, path: Path, *, owner_ref: str) -> dict[str, Any]:
        validate_local_identifier(owner_ref, "owner_ref")
        repo = _repo(path)
        if repo != default_user_strategy_library(owner_ref).resolve():
            raise ValueError("canonical strategy library must use the unified user layout")
        if _owner(repo) != owner_ref:
            raise ValueError("canonical strategy repo owner does not match")
        common = Path(_git(repo, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = (repo / common).resolve()
        value = {
            "schema_version": 1,
            "canonical_repo_ref": f"local-strategy-git://{sha256(str(repo).encode()).hexdigest()[:16]}",
            "path": str(repo),
            "owner_ref": owner_ref,
            "registered_head": _git(repo, "rev-parse", "HEAD"),
            "git_common_dir": str(common),
            "registered_at": utc_now(),
        }
        write_json(self.path, value)
        self.path.chmod(0o600)
        return value

    def load(self) -> dict[str, Any]:
        value = read_json(self.path)
        required = {
            "schema_version", "canonical_repo_ref", "path", "owner_ref",
            "registered_head", "git_common_dir", "registered_at",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("canonical strategy repo is not registered")
        repo = _repo(Path(str(value["path"])))
        if _owner(repo) != value["owner_ref"]:
            raise ValueError("canonical strategy repo owner changed")
        return value


def strategy_manifest(repo: Path, *, owner_ref: str) -> dict[str, Any]:
    """Create the source-only manifest; no factor files are implied."""
    body = {
        "schema_version": 1,
        "kind": "strategy-source",
        "owner_ref": owner_ref,
        "created_at": utc_now(),
        "source_root": "strategies",
        "actor_contract": "native-strategy-actor-v1",
    }
    return {**body, "manifest_hash": json_hash(body)}


def initialize_strategy_repo(path: Path, *, owner_ref: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path != default_user_strategy_library(owner_ref).resolve():
        raise ValueError("strategy library must use the unified user layout")
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    manifest_path = path / ".strategy_workspace" / "manifest.json"
    if manifest_path.exists():
        return read_json(manifest_path) or {}
    value = strategy_manifest(path, owner_ref=owner_ref)
    write_json(manifest_path, value)
    return value
