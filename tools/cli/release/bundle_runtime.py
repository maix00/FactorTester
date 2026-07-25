"""Activate the verified standalone CLI runtime embedded in FTClient.app."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any
import uuid

from .locations import validate_client_root
from .materialize import (
    install_stable_launchers,
    stable_launchers_are_current,
)
from .storage import json_hash, read_json, utc_now


COMMANDS = ("factortester", "cli-anything-factortester-research")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
Checkpoint = Callable[[str], None]


def activate_bundled_runtime(
    bundle_resources: Path,
    client_root: Path,
    *,
    checkpoint: Checkpoint | None = None,
) -> dict[str, Any]:
    """Install once, then atomically select one bundle-owned runtime.

    This function is deliberately local-only. It reads one bundle receipt,
    copies two verified Mach-O commands into a versioned directory, and changes
    the current pointer only after the directory is durable.
    """
    root = validate_client_root(client_root)
    root.mkdir(parents=True, exist_ok=True)
    with _activation_lock(root):
        return _activate_locked(
            bundle_resources.expanduser().resolve(),
            root,
            checkpoint=checkpoint,
        )


def _activate_locked(
    resources: Path,
    root: Path,
    *,
    checkpoint: Checkpoint | None,
) -> dict[str, Any]:
    bundle_receipt = _validated_bundle_receipt(resources)
    version = str(bundle_receipt["version"])
    receipt_hash = json_hash(bundle_receipt)
    target = root / "releases" / version
    current = read_json(root / "current.json") or {}
    existing = _installed_receipt(target)

    if existing is not None:
        if existing.get("bundle_receipt_hash") != receipt_hash:
            raise ValueError("installed bundle runtime conflicts with this app")
        _verify_installed_commands(target, existing)
        pointer_is_current = (
            current.get("version") == version
            and current.get("manifest_hash") == receipt_hash
        )
        if pointer_is_current and stable_launchers_are_current(root):
            return _result(root, version, activated=False, receipt=existing)
        install_stable_launchers(root)
        if pointer_is_current:
            return _result(root, version, activated=True, receipt=existing)
        _checkpoint(checkpoint, "before_pointer")
        _write_pointer(root, version, receipt_hash)
        return _result(root, version, activated=True, receipt=existing)

    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    staging = releases / f".staging-bundle-{version}-{uuid.uuid4().hex}"
    try:
        commands = _stage_commands(resources, staging, bundle_receipt)
        receipt = _build_receipt(
            version=version,
            source_revision=str(bundle_receipt["source_revision"]),
            bundle_receipt_hash=receipt_hash,
            previous_version=str(current.get("version") or ""),
            commands=commands,
        )
        _write_json_durable(staging / "receipt.json", receipt)
        _fsync_directory(staging)
        _checkpoint(checkpoint, "before_publish")
        os.replace(staging, target)
        _fsync_directory(releases)
        install_stable_launchers(root)
        _checkpoint(checkpoint, "before_pointer")
        _write_pointer(root, version, receipt_hash)
        return _result(root, version, activated=True, receipt=receipt)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


@contextmanager
def _activation_lock(root: Path):
    path = root / ".bundle-runtime.lock"
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validated_bundle_receipt(resources: Path) -> dict[str, Any]:
    receipt = read_json(resources / "bundle-receipt.json")
    if receipt is None or receipt.get("schema_version") != 1:
        raise ValueError("bundle runtime receipt is missing or unsupported")
    version = str(receipt.get("version") or "")
    revision = str(receipt.get("source_revision") or "")
    files = receipt.get("files")
    if not _VERSION.fullmatch(version):
        raise ValueError("bundle runtime version is invalid")
    if not _REVISION.fullmatch(revision):
        raise ValueError("bundle runtime source revision is invalid")
    if not isinstance(files, dict):
        raise ValueError("bundle runtime file hashes are missing")
    for command in COMMANDS:
        relative = f"bin/{command}"
        expected = str(files.get(relative) or "")
        if not _SHA256.fullmatch(expected):
            raise ValueError(f"bundle runtime hash is invalid: {relative}")
        source = resources / relative
        _verify_source_identity(source)
    return receipt


def _verify_source_identity(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bundle runtime command is not a regular file: {path.name}")
    mode = path.stat().st_mode
    if not mode & stat.S_IXUSR:
        raise ValueError(f"bundle runtime command is not executable: {path.name}")
    with path.open("rb") as handle:
        prefix = handle.read(4)
    if prefix in {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }:
        return
    if prefix == b"#!":
        return
    raise ValueError(
        f"bundle runtime command is neither Mach-O nor executable script: {path.name}"
    )


def _stage_commands(
    resources: Path,
    staging: Path,
    bundle_receipt: dict[str, Any],
) -> dict[str, str]:
    destination = staging / "runtime" / "standalone" / "bin"
    destination.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for command in COMMANDS:
        relative = f"bin/{command}"
        source = resources / relative
        target = destination / command
        _copy_durable(source, target)
        observed = _file_hash(target)
        expected = str(bundle_receipt["files"][relative])
        if observed != expected:
            raise ValueError(f"staged runtime checksum mismatch: {command}")
        hashes[command] = observed
    _fsync_directory(destination)
    return hashes


def _copy_durable(source: Path, target: Path) -> None:
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    target.chmod(0o755)


def _installed_receipt(target: Path) -> dict[str, Any] | None:
    receipt = read_json(target / "receipt.json")
    if receipt is None:
        if target.exists():
            raise ValueError("installed bundle runtime has no receipt")
        return None
    declared = str(receipt.get("receipt_hash") or "")
    body = dict(receipt)
    body.pop("receipt_hash", None)
    if declared != json_hash(body):
        raise ValueError("installed bundle runtime receipt is corrupt")
    standalone = (receipt.get("materialized") or {}).get("standalone") or {}
    if standalone.get("commands") != list(COMMANDS):
        raise ValueError("installed bundle runtime command identity is invalid")
    return receipt


def _verify_installed_commands(
    target: Path,
    receipt: dict[str, Any],
) -> None:
    expected = (
        (receipt.get("materialized") or {})
        .get("standalone", {})
        .get("hashes", {})
    )
    for command in COMMANDS:
        executable = target / "runtime" / "standalone" / "bin" / command
        if (
            executable.is_symlink()
            or not executable.is_file()
            or _file_hash(executable) != expected.get(command)
        ):
            raise ValueError(f"installed bundle runtime is tampered: {command}")


def _build_receipt(
    *,
    version: str,
    source_revision: str,
    bundle_receipt_hash: str,
    previous_version: str,
    commands: dict[str, str],
) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "release_id": f"ftclient-bundle-{version}",
        "version": version,
        "source_revision": source_revision,
        "manifest_hash": bundle_receipt_hash,
        "bundle_receipt_hash": bundle_receipt_hash,
        "previous_version": previous_version or None,
        "installed_at": utc_now(),
        "assets": [],
        "materialized": {
            "schema_version": 1,
            "standalone": {
                "runtime": "runtime/standalone",
                "commands": list(COMMANDS),
                "hashes": commands,
            },
        },
    }
    return {**body, "receipt_hash": json_hash(body)}


def _write_pointer(root: Path, version: str, receipt_hash: str) -> None:
    _write_json_durable(root / "current.json", {
        "schema_version": 1,
        "version": version,
        "manifest_hash": receipt_hash,
        "updated_at": utc_now(),
    })
    _fsync_directory(root)


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _checkpoint(callback: Checkpoint | None, name: str) -> None:
    if callback is not None:
        callback(name)


def _result(
    root: Path,
    version: str,
    *,
    activated: bool,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "activated": activated,
        "current_version": version,
        "install_root": str(root),
        "receipt_hash": receipt["receipt_hash"],
    }
