"""Compact verified unified-layout quarantine checkouts into rebuildable evidence."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
from typing import Any
from uuid import uuid4

from .factor_worktree import CanonicalFactorRepoStore
from .local_profile import LocalProfileStore
from .local_profile_contracts import validate_local_identifier
from .locations import validate_client_root
from .storage import json_hash, read_json, utc_now, write_json
from .user_layout_migration import _load_receipt as _load_layout_receipt


def plan_quarantine_compaction(
    client_root: Path,
    migration_id: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    migration = _load_layout_receipt(root, migration_id)
    canonical = Path(migration["canonical_mapping"]["new_path"])
    canonical_commits = set(
        _git(canonical, "rev-list", "--all").splitlines()
    )
    profiles = LocalProfileStore(root).list()
    entries = []
    for mapping in migration["legacy_quarantine"]:
        path = Path(mapping["target"]).resolve()
        if not path.is_dir():
            raise ValueError(f"quarantine path is missing: {path}")
        unsafe = _unsafe_symlinks(path)
        refs = _active_refs(profiles, path)
        git = _is_git(path)
        if git:
            status = _git_bytes(path, "status", "--porcelain=v1", "-z")
            branch = _git(path, "branch", "--show-current").strip()
            head = _git(path, "rev-parse", "HEAD").strip()
            ref_rows = _git_refs(path)
            status_context = _status_context(path)
            repo_commits = set(
                _git(path, "rev-list", "--all").splitlines()
            )
            reachable = repo_commits <= canonical_commits
            mode = "reachable_patch" if reachable else "independent_bundle"
            unique = len(repo_commits - canonical_commits)
            untracked = _untracked_manifest(path)
            refs_hash = sha256(
                json.dumps(
                    ref_rows, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        else:
            status = b""
            branch = ""
            head = ""
            ref_rows = []
            reachable = False
            mode = "content_archive"
            unique = None
            untracked = _content_manifest(path)
            refs_hash = ""
            status_context = {}
        item = {
            "path": str(path),
            "original_path": mapping["source"],
            "canonical_path": str(canonical),
            "profile_id": mapping["profile_id"],
            "migration_content_sha256": mapping["content_sha256"],
            "worktree_content_sha256": _worktree_content_hash(path),
            "before_bytes": _tree_bytes(path),
            "git": git,
            "mode": mode,
            "branch": branch,
            "head": head,
            "status_sha256": sha256(status).hexdigest(),
            "refs": ref_rows,
            "refs_sha256": refs_hash,
            "unique_commit_count": unique,
            "canonical_reachable": reachable,
            "untracked": untracked,
            "status_context": status_context,
            "unsafe_symlinks": unsafe,
            "active_profile_refs": refs,
        }
        item["safe_to_compact"] = not unsafe and not refs
        entries.append(item)
    body = {
        "schema_version": 1,
        "operation": "legacy_quarantine_compaction",
        "migration_id": migration_id,
        "canonical_path": str(canonical),
        "canonical_repo_ref": migration["canonical_mapping"]["new_ref"],
        "entries": entries,
        "safe_to_compact": bool(entries) and all(
            item["safe_to_compact"] for item in entries
        ),
        "default_action": "retain_full_checkout",
        "full_checkout_removed": False,
    }
    body["plan_hash"] = json_hash(body)
    return body


def apply_quarantine_compaction(
    client_root: Path,
    plan: dict[str, Any],
    *,
    checkpoint=None,
) -> dict[str, Any]:
    _validate_plan(plan)
    root = validate_client_root(client_root)
    observed = plan_quarantine_compaction(root, plan["migration_id"])
    if observed["plan_hash"] != plan["plan_hash"]:
        raise ValueError("quarantine changed after compaction plan")
    if not plan["safe_to_compact"]:
        raise ValueError("quarantine compaction safety gates did not pass")
    receipt_path = _receipt_path(root, plan["plan_hash"])
    existing = read_json(receipt_path)
    if existing:
        return {**existing, "receipt_ref": receipt_path.resolve().as_uri()}
    canonical = Path(plan["canonical_path"])
    published: list[dict[str, Any]] = []
    temporary_paths: list[Path] = []
    try:
        mappings = []
        for index, item in enumerate(plan["entries"]):
            source = Path(item["path"])
            staging = source.parent / (
                f".{source.name}.{plan['plan_hash'][:12]}.compact-staging"
            )
            rebuild = source.parent / (
                f".{source.name}.{plan['plan_hash'][:12]}.verify-rebuild"
            )
            if staging.exists() or rebuild.exists():
                raise ValueError("quarantine compaction staging collision")
            staging.mkdir()
            temporary_paths.extend((staging, rebuild))
            _write_compact_evidence(source, staging, item)
            _rebuild_from_evidence(staging, rebuild, canonical)
            _assert_rebuild(item, rebuild)
            shutil.rmtree(rebuild)
            before = item["before_bytes"]
            after = _tree_bytes(staging)
            backup = source.parent / (
                f".{source.name}.{plan['plan_hash'][:12]}.full-backup"
            )
            os.replace(source, backup)
            try:
                os.replace(staging, source)
            except Exception:
                os.replace(backup, source)
                raise
            published.append({
                "source": source,
                "backup": backup,
                "item": item,
            })
            shutil.rmtree(backup)
            mappings.append({
                "path": str(source),
                "original_path": item["original_path"],
                "mode": item["mode"],
                "branch": item["branch"],
                "head": item["head"],
                "status_sha256": item["status_sha256"],
                "worktree_content_sha256": item[
                    "worktree_content_sha256"
                ],
                "refs_sha256": item["refs_sha256"],
                "before_bytes": before,
                "after_bytes": after,
                "bytes_saved": max(0, before - after),
            })
            if checkpoint is not None:
                checkpoint(f"after_publish_{index}")
        body = {
            "schema_version": 1,
            "operation": "legacy_quarantine_compaction",
            "compaction_id": f"compact-{plan['plan_hash'][:16]}",
            "migration_id": plan["migration_id"],
            "canonical_path": plan["canonical_path"],
            "status": "compacted",
            "plan_hash": plan["plan_hash"],
            "mappings": mappings,
            "before_bytes": sum(
                item["before_bytes"] for item in mappings
            ),
            "after_bytes": sum(
                item["after_bytes"] for item in mappings
            ),
            "full_checkout_removed": True,
            "rebuild_verified": True,
            "unique_evidence_retained": True,
            "compacted_at": utc_now(),
        }
        body["bytes_saved"] = max(
            0, body["before_bytes"] - body["after_bytes"]
        )
        receipt = {**body, "receipt_hash": json_hash(body)}
        write_json(receipt_path, receipt)
        receipt_path.chmod(0o600)
        return {**receipt, "receipt_ref": receipt_path.resolve().as_uri()}
    except Exception:
        for entry in reversed(published):
            compact = entry["source"]
            restore = compact.parent / f".{compact.name}.failure-restore"
            _rebuild_from_evidence(compact, restore, canonical)
            _assert_rebuild(entry["item"], restore)
            shutil.rmtree(compact)
            os.replace(restore, compact)
        for path in temporary_paths:
            if path.exists():
                shutil.rmtree(path)
        raise


def verify_quarantine_compaction(
    client_root: Path,
    plan_hash: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, plan_hash)
    plan = _load_plan_from_compact_paths(receipt)
    canonical = Path(plan["canonical_path"])
    checks = []
    for item in plan["entries"]:
        compact = Path(item["path"])
        rebuild = compact.parent / (
            f".{compact.name}.{plan_hash[:12]}.verify"
        )
        if rebuild.exists():
            raise ValueError("quarantine verification staging collision")
        try:
            _rebuild_from_evidence(compact, rebuild, canonical)
            _assert_rebuild(item, rebuild)
            checks.append({
                "path": str(compact),
                "compact_present": compact.is_dir(),
                "rebuild_verified": True,
                "worktree_content_sha256": item[
                    "worktree_content_sha256"
                ],
            })
        finally:
            if rebuild.exists():
                shutil.rmtree(rebuild)
    return {
        "schema_version": 1,
        "operation": "verify_legacy_quarantine_compaction",
        "plan_hash": plan_hash,
        "valid": len(checks) == len(plan["entries"]),
        "checks": checks,
        "before_bytes": receipt["before_bytes"],
        "after_bytes": receipt["after_bytes"],
        "receipt_ref": _receipt_path(root, plan_hash).resolve().as_uri(),
    }


def rollback_quarantine_compaction(
    client_root: Path,
    plan_hash: str,
) -> dict[str, Any]:
    root = validate_client_root(client_root)
    receipt = _load_receipt(root, plan_hash)
    rollback_path = _rollback_receipt_path(root, plan_hash)
    existing = read_json(rollback_path)
    if existing:
        return {**existing, "receipt_ref": rollback_path.resolve().as_uri()}
    plan = _load_plan_from_compact_paths(receipt)
    canonical = Path(plan["canonical_path"])
    restored = []
    temporary_paths: list[Path] = []
    try:
        mappings = []
        for item in plan["entries"]:
            compact = Path(item["path"])
            rebuild = compact.parent / f".{compact.name}.rollback-rebuild"
            if rebuild.exists():
                raise ValueError("quarantine rollback staging collision")
            temporary_paths.append(rebuild)
            _rebuild_from_evidence(compact, rebuild, canonical)
            _assert_rebuild(item, rebuild)
            backup = compact.parent / f".{compact.name}.compact-backup"
            os.replace(compact, backup)
            try:
                os.replace(rebuild, compact)
            except Exception:
                os.replace(backup, compact)
                raise
            restored.append((compact, backup, item))
            shutil.rmtree(backup)
            mappings.append({
                "path": str(compact),
                "worktree_content_sha256": item[
                    "worktree_content_sha256"
                ],
                "branch": item["branch"],
                "head": item["head"],
                "status_sha256": item["status_sha256"],
            })
        body = {
            "schema_version": 1,
            "operation": "rollback_legacy_quarantine_compaction",
            "plan_hash": plan_hash,
            "status": "full_checkouts_restored",
            "mappings": mappings,
            "content_verified": True,
            "rolled_back_at": utc_now(),
        }
        value = {**body, "receipt_hash": json_hash(body)}
        write_json(rollback_path, value)
        rollback_path.chmod(0o600)
        return {**value, "receipt_ref": rollback_path.resolve().as_uri()}
    except Exception:
        for compact, _, item in reversed(restored):
            staging = compact.parent / f".{compact.name}.recompact"
            staging.mkdir()
            _write_compact_evidence(compact, staging, item)
            shutil.rmtree(compact)
            os.replace(staging, compact)
        for path in temporary_paths:
            if path.exists():
                shutil.rmtree(path)
        raise


def _write_compact_evidence(
    source: Path,
    destination: Path,
    item: dict[str, Any],
) -> None:
    evidence = {**item, "schema_version": 1}
    write_json(destination / "compact-manifest.json", evidence)
    if item["git"]:
        (destination / "tracked-index.patch").write_bytes(
            _git_bytes(source, "diff", "--cached", "--binary", "HEAD")
        )
        (destination / "tracked-worktree.patch").write_bytes(
            _git_bytes(source, "diff", "--binary")
        )
        _write_tar(
            source, destination / "untracked.tar.gz",
            [entry["path"] for entry in item["untracked"]],
        )
        if item["mode"] == "independent_bundle":
            _git(
                source, "bundle", "create",
                str(destination / "history.bundle"), "--all",
            )
    else:
        _write_tar(
            source,
            destination / "content.tar.gz",
            [entry["path"] for entry in item["untracked"]],
        )


def _rebuild_from_evidence(
    compact: Path,
    destination: Path,
    canonical: Path,
) -> None:
    manifest = read_json(compact / "compact-manifest.json")
    if not manifest:
        raise ValueError("compact evidence manifest is missing")
    mode = manifest["mode"]
    if mode == "content_archive":
        destination.mkdir()
        _extract_tar(compact / "content.tar.gz", destination)
        return
    source = (
        compact / "history.bundle"
        if mode == "independent_bundle" else canonical
    )
    result = subprocess.run(
        ["git", "clone", "--no-checkout", str(source), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot rebuild compact Git evidence: {result.stderr}")
    head = manifest["head"]
    branch = manifest["branch"]
    if branch:
        _git(destination, "checkout", "-B", branch, head)
    else:
        _git(destination, "checkout", "--detach", head)
    index_patch = compact / "tracked-index.patch"
    worktree_patch = compact / "tracked-worktree.patch"
    if index_patch.stat().st_size:
        _git(destination, "apply", "--index", str(index_patch))
    if worktree_patch.stat().st_size:
        _git(destination, "apply", str(worktree_patch))
    _restore_status_context(destination, manifest["status_context"])
    _extract_tar(compact / "untracked.tar.gz", destination)
    _restore_refs(destination, manifest["refs"])


def _assert_rebuild(item: dict[str, Any], rebuilt: Path) -> None:
    if _worktree_content_hash(rebuilt) != item["worktree_content_sha256"]:
        raise ValueError("compact evidence content reconstruction failed")
    if not item["git"]:
        return
    if _git(rebuilt, "rev-parse", "HEAD").strip() != item["head"]:
        raise ValueError("compact evidence HEAD reconstruction failed")
    if _git(rebuilt, "branch", "--show-current").strip() != item["branch"]:
        raise ValueError("compact evidence branch reconstruction failed")
    status = _git_bytes(rebuilt, "status", "--porcelain=v1", "-z")
    if sha256(status).hexdigest() != item["status_sha256"]:
        raise ValueError("compact evidence status reconstruction failed")
    if _refs_hash(_git_refs(rebuilt)) != item["refs_sha256"]:
        raise ValueError("compact evidence refs reconstruction failed")


def _load_plan_from_compact_paths(
    receipt: dict[str, Any],
) -> dict[str, Any]:
    entries = []
    for mapping in receipt["mappings"]:
        compact = Path(mapping["path"])
        item = read_json(compact / "compact-manifest.json")
        if not item:
            raise ValueError("compact evidence manifest is missing")
        for key in (
            "path", "original_path", "mode", "branch", "head",
            "status_sha256", "worktree_content_sha256", "refs_sha256",
        ):
            if item.get(key) != mapping.get(key):
                raise ValueError("compact evidence manifest conflicts with receipt")
        entries.append(item)
    return {
        "entries": entries,
        "canonical_path": receipt["canonical_path"],
    }


def _active_refs(
    profiles: list[dict[str, Any]],
    path: Path,
) -> list[dict[str, str]]:
    refs = []
    for profile in profiles:
        if Path(profile["workspace_root"]).resolve() == path:
            refs.append({"profile_id": profile["profile_id"], "kind": "root"})
        for workspace in profile["workspaces"]:
            if Path(workspace["path"]).resolve() == path:
                refs.append({
                    "profile_id": profile["profile_id"],
                    "kind": f"workspace:{workspace['workspace_id']}",
                })
        binding = profile.get("factor_workspace_binding") or {}
        if binding and Path(binding["worktree_path"]).resolve() == path:
            refs.append({
                "profile_id": profile["profile_id"],
                "kind": "factor_worktree",
            })
    return refs


def _git_refs(repo: Path) -> list[dict[str, str]]:
    rows = []
    for line in _git(
        repo, "for-each-ref", "--format=%(refname)%00%(objectname)"
    ).splitlines():
        ref, _, commit = line.partition("\0")
        rows.append({"ref": ref, "commit": commit})
    return rows


def _untracked_manifest(repo: Path) -> list[dict[str, Any]]:
    tracked = {
        value.decode()
        for value in _git_bytes(repo, "ls-files", "-z").split(b"\0")
        if value
    }
    paths = [
        str(path.relative_to(repo))
        for path in sorted(repo.rglob("*"))
        if (
            (path.is_file() or path.is_symlink())
            and path.relative_to(repo).parts[:1] != (".git",)
            and str(path.relative_to(repo)) not in tracked
        )
    ]
    return _paths_manifest(repo, paths)


def _content_manifest(root: Path) -> list[dict[str, Any]]:
    return _paths_manifest(
        root,
        [
            str(path.relative_to(root))
            for path in sorted(root.rglob("*"))
            if path.is_file() or path.is_symlink() or path.is_dir()
        ],
    )


def _paths_manifest(
    root: Path,
    paths: list[str],
) -> list[dict[str, Any]]:
    entries = []
    for relative in paths:
        path = root / relative
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            entries.append({
                "path": relative,
                "kind": "symlink",
                "mode": mode,
                "sha256": sha256(
                    str(path.readlink()).encode()
                ).hexdigest(),
            })
        elif path.is_file():
            entries.append({
                "path": relative,
                "kind": "file",
                "mode": mode,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            })
        elif path.is_dir():
            entries.append({
                "path": relative,
                "kind": "directory",
                "mode": mode,
                "sha256": "",
            })
    return entries


def _write_tar(root: Path, archive: Path, paths: list[str]) -> None:
    with tarfile.open(archive, "w:gz", dereference=False) as stream:
        for relative in sorted(paths):
            path = root / relative
            if path.is_symlink():
                try:
                    path.resolve(strict=False).relative_to(root.resolve())
                except ValueError as exc:
                    raise ValueError("unsafe symlink cannot be archived") from exc
            stream.add(path, arcname=relative, recursive=False)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            target = (destination / member.name).resolve(strict=False)
            try:
                target.relative_to(destination.resolve())
            except ValueError as exc:
                raise ValueError("compact archive contains unsafe path") from exc
        stream.extractall(destination, filter="data")


def _worktree_content_hash(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (
            relative.parts[:1] == (".git",)
            or any(
                "compact-staging" in part
                or "verify-rebuild" in part
                or "rollback-rebuild" in part
                for part in relative.parts
            )
        ):
            continue
        if path.is_symlink():
            digest.update(str(relative).encode())
            digest.update(b"link:")
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(str(relative).encode())
            digest.update(b"file:")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _restore_refs(repo: Path, expected: list[dict[str, str]]) -> None:
    expected_by_ref = {
        str(item["ref"]): str(item["commit"]) for item in expected
    }
    for item in _git_refs(repo):
        if item["ref"] not in expected_by_ref:
            _git(repo, "update-ref", "-d", item["ref"])
    for ref, commit in expected_by_ref.items():
        _git(repo, "update-ref", ref, commit)


def _status_context(repo: Path) -> dict[str, str]:
    exclude_path = Path(
        _git(repo, "rev-parse", "--git-path", "info/exclude").strip()
    )
    if not exclude_path.is_absolute():
        exclude_path = repo / exclude_path
    configured = subprocess.run(
        ["git", "-C", str(repo), "config", "--path", "--get", "core.excludesFile"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    configured_path = Path(configured).expanduser() if configured else None
    return {
        "info_exclude": (
            exclude_path.read_text(encoding="utf-8")
            if exclude_path.is_file() else ""
        ),
        "configured_excludes": (
            configured_path.read_text(encoding="utf-8")
            if configured_path is not None and configured_path.is_file()
            else ""
        ),
    }


def _restore_status_context(
    repo: Path,
    context: dict[str, str],
) -> None:
    exclude_path = Path(
        _git(repo, "rev-parse", "--git-path", "info/exclude").strip()
    )
    if not exclude_path.is_absolute():
        exclude_path = repo / exclude_path
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    exclude_path.write_text(context.get("info_exclude", ""), encoding="utf-8")
    configured = context.get("configured_excludes", "")
    if configured:
        configured_path = exclude_path.parent / "compact-global-excludes"
        configured_path.write_text(configured, encoding="utf-8")
        _git(repo, "config", "core.excludesFile", str(configured_path))
    else:
        subprocess.run(
            ["git", "-C", str(repo), "config", "--unset-all", "core.excludesFile"],
            capture_output=True,
            check=False,
        )


def _refs_hash(rows: list[dict[str, str]]) -> str:
    return sha256(
        json.dumps(
            rows, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _unsafe_symlinks(root: Path) -> list[str]:
    unsafe = []
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=False).relative_to(root.resolve())
        except ValueError:
            unsafe.append(str(path.relative_to(root)))
    return sorted(unsafe)


def _is_git(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _tree_bytes(root: Path) -> int:
    return sum(
        path.lstat().st_size for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _validate_plan(plan: dict[str, Any]) -> None:
    body = dict(plan)
    declared = str(body.pop("plan_hash", ""))
    if (
        plan.get("schema_version") != 1
        or plan.get("operation") != "legacy_quarantine_compaction"
        or declared != json_hash(body)
    ):
        raise ValueError("legacy quarantine compaction plan is invalid")


def _load_receipt(root: Path, plan_hash: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("quarantine compaction plan hash is invalid")
    value = read_json(_receipt_path(root, plan_hash))
    if not value:
        raise ValueError("quarantine compaction receipt not found")
    body = dict(value)
    declared = str(body.pop("receipt_hash", ""))
    if declared != json_hash(body):
        raise ValueError("quarantine compaction receipt is corrupt")
    return value


def _receipt_path(root: Path, plan_hash: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("quarantine compaction plan hash is invalid")
    return (
        validate_client_root(root) / "profiles"
        / "quarantine-compaction-receipts" / f"{plan_hash}.json"
    )


def _rollback_receipt_path(root: Path, plan_hash: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("quarantine compaction plan hash is invalid")
    return (
        validate_client_root(root) / "profiles"
        / "quarantine-compaction-receipts"
        / f"{plan_hash}.rollback.json"
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env={**os.environ, "FACTOR_WORKSPACE_SKIP_AUTOSYNC": "1"},
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed: "
            + result.stderr.decode(errors="replace")
        )
    return result.stdout
