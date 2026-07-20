"""Read-only legacy workspace audit and gated recoverable purge."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import subprocess
from typing import Any

from .factor_worktree import CanonicalFactorRepoStore
from .local_profile import LocalProfileStore
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json


def plan_legacy_workspace_cleanup(
    client_root: Path,
    workspaces: list[Path],
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    if not workspaces:
        raise ValueError("at least one legacy workspace is required")
    settings = CanonicalFactorRepoStore(root).load()
    canonical = Path(str(settings["path"])).resolve()
    canonical_head = _git_value(canonical, "rev-parse", "HEAD")
    registered = {
        Path(row["worktree"]).resolve()
        for row in _worktree_rows(canonical)
    }
    store = LocalProfileStore(root)
    profiles = store.list()
    entries = []
    seen: set[Path] = set()
    for raw in workspaces:
        path = raw.expanduser().resolve()
        if path in seen:
            raise ValueError(f"duplicate legacy workspace: {path}")
        seen.add(path)
        if not path.is_dir():
            raise ValueError(f"legacy workspace not found: {path}")
        status = _git_bytes(path, "status", "--porcelain=v1", "-z")
        head = _git_value(path, "rev-parse", "HEAD")
        branch = _git_value(path, "branch", "--show-current")
        unique = _unique_commits(path, canonical_head, head)
        references = _profile_references(profiles, path)
        unsafe_links = _unsafe_symlinks(path)
        managed_root = (
            Path.home() / "Documents" / "FactorTester"
        ).expanduser().resolve()
        protected = {
            managed_root,
            managed_root / "profiles",
            managed_root / "personal-workspaces",
        }
        managed = _within(path, managed_root) and path not in protected
        content_hash = _content_hash(path)
        entry = {
            "path": str(path),
            "branch": branch,
            "head": head,
            "dirty": bool(status),
            "dirty_file_count": len(
                [item for item in status.split(b"\0") if item]
            ),
            "status_sha256": sha256(status).hexdigest(),
            "unique_commit_count": unique,
            "content_sha256": content_hash,
            "git_refs_sha256": _refs_hash(path),
            "profile_refs": references,
            "registered_worktree": path in registered,
            "canonical_workspace": path == canonical,
            "unsafe_symlinks": unsafe_links,
            "within_managed_root": managed,
            "protected_container": path in protected,
        }
        entry["safe_to_purge"] = (
            managed
            and not entry["dirty"]
            and unique == 0
            and not references
            and not entry["registered_worktree"]
            and not entry["canonical_workspace"]
            and not unsafe_links
        )
        entries.append(entry)
    body = {
        "schema_version": 1,
        "operation": "legacy_personal_workspace_cleanup",
        "canonical_repo_ref": settings["canonical_repo_ref"],
        "canonical_head": canonical_head,
        "entries": entries,
        "safe_to_purge": all(item["safe_to_purge"] for item in entries),
        "default_action": "retain",
        "destructive_action_performed": False,
    }
    body["plan_hash"] = json_hash(body)
    return body


def purge_legacy_workspaces(
    client_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    _validate_plan(plan)
    root = validate_client_root(client_root)
    receipt_path = _receipt_path(root, str(plan["plan_hash"]))
    existing = read_json(receipt_path)
    if existing is not None:
        return {**existing, "receipt_ref": receipt_path.resolve().as_uri()}
    observed = plan_legacy_workspace_cleanup(
        root, [Path(item["path"]) for item in plan["entries"]]
    )
    if observed["plan_hash"] != plan["plan_hash"]:
        raise ValueError("legacy workspace changed after cleanup plan")
    if not observed["safe_to_purge"]:
        raise ValueError("legacy workspace purge safety gates did not pass")
    purge_id = f"legacy-{plan['plan_hash'][:16]}"
    quarantine = (
        root / "profiles" / "legacy-workspace-quarantine" / purge_id
    )
    if quarantine.exists():
        raise ValueError("legacy workspace quarantine collision")
    quarantine.mkdir(parents=True)
    mappings = []
    try:
        for index, item in enumerate(plan["entries"]):
            source = Path(item["path"])
            target = quarantine / f"{index:03d}-{source.name}"
            if source.stat().st_dev != quarantine.stat().st_dev:
                raise ValueError(
                    "legacy purge requires same-volume recoverable quarantine"
                )
            os.replace(source, target)
            mappings.append({
                "source": str(source),
                "quarantine": str(target),
                "content_sha256": item["content_sha256"],
                "head": item["head"],
                "branch": item["branch"],
            })
        body = {
            "schema_version": 1,
            "operation": "legacy_personal_workspace_purge",
            "purge_id": purge_id,
            "status": "quarantined",
            "plan_hash": plan["plan_hash"],
            "mappings": mappings,
            "branches_retained": True,
            "commits_retained": True,
            "content_retained": True,
            "purged_at": utc_now(),
        }
        receipt = {**body, "receipt_hash": json_hash(body)}
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        return {**receipt, "receipt_ref": receipt_path.resolve().as_uri()}
    except Exception:
        for item in reversed(mappings):
            target = Path(item["quarantine"])
            source = Path(item["source"])
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, source)
        if quarantine.exists() and not any(quarantine.iterdir()):
            quarantine.rmdir()
        raise


def _profile_references(
    profiles: list[dict[str, Any]],
    path: Path,
) -> list[dict[str, str]]:
    refs = []
    for profile in profiles:
        profile_id = str(profile["profile_id"])
        if Path(str(profile["workspace_root"])).resolve() == path:
            refs.append({"profile_id": profile_id, "kind": "workspace_root"})
        for workspace in profile["workspaces"]:
            if Path(str(workspace["path"])).resolve() == path:
                refs.append({
                    "profile_id": profile_id,
                    "kind": f"workspace:{workspace['workspace_id']}",
                })
        binding = profile.get("factor_workspace_binding") or {}
        if (
            binding
            and Path(str(binding["worktree_path"])).resolve() == path
        ):
            refs.append({
                "profile_id": profile_id,
                "kind": f"factor_worktree:{binding['binding_id']}",
            })
    return refs


def _unique_commits(repo: Path, base: str, head: str) -> int | None:
    if not base or not head:
        return None
    result = _git_result(repo, "rev-list", "--count", f"{base}..{head}")
    if result.returncode:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _worktree_rows(repo: Path) -> list[dict[str, str]]:
    rows, current = [], {}
    for line in _git_value(repo, "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        rows.append(current)
    return rows


def _content_hash(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[:1] == (".git",):
            continue
        digest.update(str(relative).encode())
        if path.is_symlink():
            digest.update(b"link:")
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(b"file:")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _refs_hash(repo: Path) -> str:
    result = _git_result(repo, "show-ref")
    return (
        sha256(result.stdout.encode()).hexdigest()
        if result.returncode == 0 else ""
    )


def _unsafe_symlinks(root: Path) -> list[str]:
    unsafe = []
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError:
            unsafe.append(str(path.relative_to(root)))
    return sorted(unsafe)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


def _validate_plan(plan: dict[str, Any]) -> None:
    body = dict(plan)
    declared = str(body.pop("plan_hash", ""))
    if (
        plan.get("schema_version") != 1
        or plan.get("operation") != "legacy_personal_workspace_cleanup"
        or declared != json_hash(body)
    ):
        raise ValueError("legacy workspace cleanup plan is invalid")


def _receipt_path(root: Path, plan_hash: str) -> Path:
    return (
        validate_client_root(root)
        / "profiles"
        / "legacy-workspace-purge-receipts"
        / f"{plan_hash}.json"
    )


def _git_value(repo: Path, *args: str) -> str:
    result = _git_result(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else b""


def _git_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
