"""Review and move one local root without copying credentials or user data.

This is an explicit, offline maintenance operation. The temporary legacy
symlink preserves older absolute worktree paths until every consumer has
migrated; it is not removed automatically.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


def _roots(kind: str, home: Path) -> tuple[Path, Path]:
    if kind == "cli":
        return home / ".factortester", home / ".traderesearch"
    if kind == "documents":
        return home / "Documents" / "FactorTester", home / "Documents" / "TradeResearch"
    raise ValueError("unknown local root")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                      separators=(",", ":")).encode()).hexdigest()


def _inventory(root: Path) -> dict[str, Any]:
    """Hash path metadata, never file content; a move retains existing inodes."""
    digest = hashlib.sha256()
    count = size = 0
    pending = [root]
    while pending:
        path = pending.pop()
        value = path.lstat()
        name = str(path.relative_to(root))
        item = [name, value.st_dev, value.st_ino, value.st_mode,
                getattr(value, "st_uid", None), getattr(value, "st_gid", None),
                value.st_size, value.st_mtime_ns]
        if stat.S_ISLNK(value.st_mode):
            item.append(os.readlink(path))
        digest.update(json.dumps(item, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
        count += 1
        if stat.S_ISREG(value.st_mode):
            size += value.st_size
        if stat.S_ISDIR(value.st_mode):
            with os.scandir(path) as entries:
                pending.extend(sorted((Path(entry.path) for entry in entries),
                                      key=lambda entry: entry.name, reverse=True))
    return {"entries": count, "bytes": size, "metadata_sha256": digest.hexdigest()}


def plan(kind: str, *, home: Path | None = None) -> dict[str, Any]:
    home = (home or Path.home()).expanduser().resolve()
    source, target = _roots(kind, home)
    source_exists = source.exists() or source.is_symlink()
    target_exists = target.exists() or target.is_symlink()
    conflict = ""
    inventory = None
    if source_exists and target_exists:
        try:
            same = os.path.samefile(source, target)
            state = ("already_migrated" if same and source.is_symlink() and not target.is_symlink()
                     else "legacy_alias" if same and target.is_symlink() and not source.is_symlink()
                     else "conflict")
        except OSError:
            state = "conflict"
        if state == "conflict":
            conflict = "both roots exist or a link is broken"
    elif source_exists:
        if source.is_symlink() or not source.is_dir():
            state, conflict = "conflict", "legacy root is not a regular directory"
        else:
            state = "move"
            inventory = _inventory(source)
    else:
        state = "current" if target_exists and target.is_dir() else "absent"
        if target_exists and not target.is_dir():
            state, conflict = "conflict", "current root is invalid"
    value = {"version": 1, "kind": kind, "source": str(source), "target": str(target),
             "state": state, "conflict": conflict, "inventory": inventory,
             "credentials": "move existing files without copying; Keychain unchanged"}
    return {**value, "sha256": _digest(value)}


def _rename_noreplace(source: Path, target: Path) -> None:
    """Atomically refuse replacing any independently created target."""
    if os.name == "nt":
        os.rename(source, target)  # Windows rename refuses an existing target.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        call = getattr(libc, "renamex_np", None)
        args = (os.fsencode(source), os.fsencode(target), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        call = getattr(libc, "renameat2", None)
        args = (-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    else:
        call = None
    if call is None:
        raise OSError(errno.ENOTSUP, "safe no-replace rename is unavailable")
    if call(*args) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(source), str(target))


def _write_receipt(path: Path, value: dict[str, Any], *, create: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | (os.O_CREAT | os.O_EXCL if create else os.O_APPEND)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_mode & 0o077)
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise PermissionError("migration receipt must be a private regular file")
        stream.write(json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_receipt(path: Path) -> list[dict[str, Any]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_mode & 0o077)
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            raise PermissionError("migration receipt must be a private regular file")
        return [json.loads(line) for line in stream if line.strip()]


def apply(kind: str, *, expected_sha256: str, receipt: Path,
          quiesced: bool, home: Path | None = None) -> dict[str, Any]:
    if not quiesced:
        raise ValueError("close clients and services using this root before migration")
    reviewed = plan(kind, home=home)
    if reviewed["state"] != "move" or reviewed["sha256"] != expected_sha256:
        raise ValueError("migration plan changed, conflicts, or has nothing to move")
    source, target = Path(reviewed["source"]), Path(reviewed["target"])
    receipt = receipt.expanduser().absolute()
    receipt_location = receipt.parent.resolve() / receipt.name
    if (receipt_location == source or receipt_location == target
            or source in receipt_location.parents or target in receipt_location.parents):
        raise ValueError("migration receipt must be outside both moved roots")
    info = source.stat()
    if source.parent.stat().st_dev != info.st_dev:
        raise ValueError("migration requires a same-volume directory move")
    _write_receipt(receipt, {"event": "intent", "plan": reviewed,
                             "device": info.st_dev, "inode": info.st_ino}, create=True)
    _rename_noreplace(source, target)
    _write_receipt(receipt, {"event": "moved"}, create=False)
    if _inventory(target) != reviewed["inventory"]:
        _rename_noreplace(target, source)
        _write_receipt(receipt, {"event": "drift_rolled_back"}, create=False)
        raise ValueError("directory changed during migration; it was moved back")
    try:
        os.symlink(target.name, source, target_is_directory=True)
    except OSError:
        # Never overwrite a concurrently-created source on rollback.
        _rename_noreplace(target, source)
        _write_receipt(receipt, {"event": "link_failed_rolled_back"}, create=False)
        raise
    _write_receipt(receipt, {"event": "applied"}, create=False)
    return {"status": "applied", "kind": kind, "compatibility_link": str(source),
            "receipt": str(receipt)}


def recover(*, receipt: Path, quiesced: bool, home: Path | None = None) -> dict[str, Any]:
    """Recover an interrupted move or rollback after verifying directory identity."""
    if not quiesced:
        raise ValueError("close clients and services using this root before recovery")
    rows = _read_receipt(receipt)
    if not rows or rows[0].get("event") != "intent":
        raise ValueError("invalid migration receipt")
    if any(row.get("event") in ("rolled_back", "link_failed_rolled_back", "drift_rolled_back") for row in rows):
        raise ValueError("rollback already completed; review the receipt")
    original = rows[0]
    reviewed = original["plan"]
    source, target = _roots(reviewed["kind"], (home or Path.home()).expanduser().resolve())
    if str(source) != reviewed["source"] or str(target) != reviewed["target"]:
        raise ValueError("receipt does not match this account")
    if any(row.get("event") == "rollback_intent" for row in rows):
        if source.is_symlink() and target.is_dir() and not target.is_symlink():
            if not os.path.samefile(source, target):
                raise ValueError("legacy link changed during rollback")
            info = target.stat()
            if (info.st_dev, info.st_ino) != (original["device"], original["inode"]):
                raise ValueError("migrated directory identity changed")
            source.unlink()
        if not source.exists() and not source.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise ValueError("migrated directory is unavailable")
            info = target.stat()
            if (info.st_dev, info.st_ino) != (original["device"], original["inode"]):
                raise ValueError("migrated directory identity changed")
            _rename_noreplace(target, source)
        if source.is_symlink() or not source.is_dir():
            raise ValueError("original directory is unavailable")
        info = source.stat()
        if (info.st_dev, info.st_ino) != (original["device"], original["inode"]):
            raise ValueError("original directory identity changed")
        if not target.exists() and not target.is_symlink():
            os.symlink(source.name, target, target_is_directory=True)
        elif not target.is_symlink() or not os.path.samefile(source, target):
            raise ValueError("current path changed during rollback")
        _write_receipt(receipt, {"event": "rolled_back"}, create=False)
        return {"status": "rolled_back", "kind": reviewed["kind"]}
    if target.is_symlink():
        raise ValueError("migrated directory was replaced by a link")
    info = target.stat()
    if (info.st_dev, info.st_ino) != (original["device"], original["inode"]):
        raise ValueError("migrated directory identity changed")
    if not source.exists() and not source.is_symlink():
        os.symlink(target.name, source, target_is_directory=True)
    elif not source.is_symlink() or not os.path.samefile(source, target):
        raise ValueError("legacy path changed during recovery")
    if not any(row.get("event") == "applied" for row in rows):
        _write_receipt(receipt, {"event": "applied"}, create=False)
    return {"status": "applied", "kind": reviewed["kind"]}


def rollback(*, receipt: Path, quiesced: bool, home: Path | None = None) -> dict[str, Any]:
    if not quiesced:
        raise ValueError("close clients and services using this root before rollback")
    rows = _read_receipt(receipt)
    if not rows or rows[0].get("event") != "intent" or not any(x.get("event") == "applied" for x in rows):
        raise ValueError("receipt does not describe an applied migration")
    if any(x.get("event") == "rolled_back" for x in rows):
        return {"status": "already_rolled_back"}
    original = rows[0]
    reviewed = original["plan"]
    source, target = _roots(reviewed["kind"], (home or Path.home()).expanduser().resolve())
    if (str(source) != reviewed["source"] or str(target) != reviewed["target"]
            or not source.is_symlink() or not os.path.samefile(source, target)):
        raise ValueError("migration links or roots changed; manual review required")
    if target.is_symlink():
        raise ValueError("migrated directory was replaced by a link")
    info = target.stat()
    if (info.st_dev, info.st_ino) != (original["device"], original["inode"]):
        raise ValueError("migrated directory identity changed")
    _write_receipt(receipt, {"event": "rollback_intent"}, create=False)
    source.unlink()
    try:
        _rename_noreplace(target, source)
    except OSError:
        if not source.exists() and not source.is_symlink():
            os.symlink(target.name, source, target_is_directory=True)
        raise
    os.symlink(source.name, target, target_is_directory=True)
    _write_receipt(receipt, {"event": "rolled_back"}, create=False)
    return {"status": "rolled_back", "kind": reviewed["kind"]}
