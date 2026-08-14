"""Filesystem and JSON state helpers for account-identity migration."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
from pathlib import Path


_TEXT_SCAN_LIMIT = 16 * 1024 * 1024


def backup_json(source: str | Path, destination: str | Path) -> None:
    """Back up a local device registry/grant file without exposing its data."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        return
    destination_path = Path(destination).expanduser().resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def backup_user_root(source: str | Path, destination: str | Path) -> None:
    """Make a complete, recoverable copy of a principal workspace tree."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_dir() or source_path.is_symlink():
        raise ValueError(f"user root is not a real directory: {source_path}")
    if destination_path == source_path or source_path in destination_path.parents:
        raise ValueError("user-root backup must be outside the source directory")
    if destination_path.exists():
        raise ValueError(f"user-root backup already exists: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_path,
        destination_path,
        symlinks=True,
        copy_function=shutil.copy2,
    )


def _rewrite_text_file(path: Path, replacements: dict[str, str]) -> bool:
    """Rewrite a bounded text file while preserving its mode."""
    if path.is_symlink():
        return False
    try:
        original = path.read_bytes()
        if len(original) > _TEXT_SCAN_LIMIT or b"\x00" in original:
            return False
        updated = original
        for old, new in replacements.items():
            updated = updated.replace(old.encode("utf-8"), new.encode("utf-8"))
        if updated == original:
            return False
        mode = stat.S_IMODE(path.stat().st_mode)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        temporary.write_bytes(updated)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        return True
    except OSError as exc:
        raise RuntimeError(f"cannot rewrite migrated workspace metadata: {path}") from exc


def rewrite_user_root_references(
    root: str | Path,
    *,
    old_username: str,
    new_username: str,
) -> dict[str, int]:
    """Repair moved workspace paths and operational Profile manifests.

    Historical evidence and report contents keep both their original
    principal values and their original bytes. Only Git worktree pointers and
    generated ``.factor_workspace/manifest.json`` files are operational
    metadata and are rewritten; changing paths inside signed evidence would
    invalidate content/envelope hashes.
    """
    root_path = Path(root).expanduser().resolve()
    parent_path = root_path.parent
    old_path = str(parent_path / old_username)
    new_path = str(parent_path / new_username)
    rewritten_paths = 0
    rewritten_manifests = 0
    for path in root_path.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        is_git_pointer = (
            path.name in {".git", "gitdir", "config.worktree"}
            or (".git" in path.parts and "worktrees" in path.parts)
        )
        is_manifest = (
            path.name == "manifest.json" and ".factor_workspace" in path.parts
        )
        if (is_git_pointer or is_manifest) and _rewrite_text_file(
            path, {old_path: new_path}
        ):
            rewritten_paths += 1
        if is_manifest:
            if _rewrite_text_file(path, {old_username: new_username}):
                rewritten_manifests += 1
    return {
        "rewritten_path_files": rewritten_paths,
        "rewritten_manifest_files": rewritten_manifests,
    }


def user_root_identity_plan(
    parent: str | Path,
    *,
    old_username: str,
    new_username: str,
) -> dict[str, object]:
    """Plan a principal-directory rename and active cleanup.

    The parent must be explicitly supplied because user workspaces can live
    on a separate data disk. The apply step archives other child directories
    into the migration backup instead of irreversibly deleting them.
    """
    root = Path(parent).expanduser().resolve()
    if not root.exists():
        return {
            "parent": str(root),
            "status": "missing",
            "old_path": str(root / old_username),
            "new_path": str(root / new_username),
            "other_directories": [],
        }
    if not root.is_dir():
        raise ValueError(f"user root parent is not a directory: {root}")
    children = sorted(
        child.name for child in root.iterdir()
        if child.is_dir() and not child.is_symlink()
        and child.name not in {old_username, new_username}
        and not child.name.startswith(".")
    )
    old_path = root / old_username
    new_path = root / new_username
    if old_path.exists() and new_path.exists():
        raise ValueError(f"both old and new user roots exist under {root}")
    return {
        "parent": str(root),
        "status": "ready",
        "old_path": str(old_path),
        "new_path": str(new_path),
        "old_exists": old_path.is_dir(),
        "new_exists": new_path.exists(),
        "other_directories": children,
    }


def apply_user_root_identity_migration(
    parent: str | Path,
    *,
    old_username: str,
    new_username: str,
    backup_root: str | Path,
    remove_other_users: bool = True,
) -> dict[str, int]:
    """Back up, rename, and repair the target user root."""
    plan = user_root_identity_plan(
        parent,
        old_username=old_username,
        new_username=new_username,
    )
    if plan.get("status") == "missing":
        return {"renamed": 0, "archived_other_roots": 0}
    root = Path(str(plan["parent"]))
    old_path = root / old_username
    new_path = root / new_username
    if not old_path.is_dir():
        return {"renamed": 0, "archived_other_roots": 0}
    if new_path.exists():
        raise ValueError(f"new user root already exists: {new_path}")
    archive = Path(backup_root).expanduser().resolve() / "user-roots"
    if archive == root or root in archive.parents:
        raise ValueError("user-root backup must be outside the user-root parent")
    archive.mkdir(parents=True, exist_ok=True)
    target_backup = archive / f"target-{old_username}"
    backup_user_root(old_path, target_backup)
    archived = 0
    if remove_other_users:
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if (
                not child.is_dir()
                or child.is_symlink()
                or child.name.startswith(".")
                or child.name in {old_username, new_username}
            ):
                continue
            destination = archive / child.name
            if destination.exists():
                raise ValueError(f"user-root backup already exists: {destination}")
            shutil.move(str(child), str(destination))
            archived += 1
    shutil.move(str(old_path), str(new_path))
    rewritten = rewrite_user_root_references(
        new_path,
        old_username=old_username,
        new_username=new_username,
    )
    return {
        "renamed": 1,
        "archived_other_roots": archived,
        "target_backup_created": 1,
        **rewritten,
    }


def migrate_local_device_json(
    path: str | Path,
    *,
    old_username: str,
    new_username: str,
    remove_other_users: bool = True,
) -> dict[str, int]:
    """Migrate usernames in local browser-device registry or grant JSON."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return {"renamed": 0, "removed": 0}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"local device JSON is invalid: {file_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"local device JSON must be an object: {file_path}")
    counts = {"renamed": 0, "removed": 0}

    def migrate_record(record: object) -> bool:
        if not isinstance(record, dict):
            # Do not destroy malformed/unowned records merely because this
            # one-time cleanup cannot attribute them to an account.
            return True
        owner = str(record.get("username") or "")
        if owner == old_username:
            record["username"] = new_username
            counts["renamed"] += 1
            return True
        if remove_other_users and owner:
            counts["removed"] += 1
            return False
        return True

    values = payload.get("authorizations")
    if isinstance(values, dict):
        payload["authorizations"] = {
            key: record for key, record in values.items()
            if migrate_record(record)
        }
    devices = payload.get("devices")
    if isinstance(devices, dict):
        payload["devices"] = {
            key: record for key, record in devices.items()
            if migrate_record(record)
        }
    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source in sources.values():
            if not isinstance(source, dict) or not isinstance(source.get("devices"), list):
                continue
            source["devices"] = [
                record for record in source["devices"]
                if migrate_record(record)
            ]
    temporary = file_path.with_name(
        f".{file_path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, file_path)
    return counts


def migrate_local_session_json(
    path: str | Path,
    *,
    old_username: str,
    new_username: str,
    remove_other_users: bool = True,
) -> dict[str, int]:
    """Update persisted Manager sessions without changing token hashes."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        return {"renamed": 0, "removed": 0}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"local session JSON is invalid: {file_path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), dict):
        raise RuntimeError(f"local session JSON is invalid: {file_path}")
    counts = {"renamed": 0, "removed": 0}
    sessions = payload["sessions"]
    result: dict[str, object] = {}
    for token_hash, record in sessions.items():
        if not isinstance(record, dict):
            result[str(token_hash)] = record
            continue
        principal = str(record.get("principal") or "")
        if principal == old_username:
            record = {**record, "principal": new_username}
            counts["renamed"] += 1
        elif remove_other_users and principal:
            counts["removed"] += 1
            continue
        result[str(token_hash)] = record
    payload["sessions"] = result
    temporary = file_path.with_name(
        f".{file_path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    os.replace(temporary, file_path)
    return counts
