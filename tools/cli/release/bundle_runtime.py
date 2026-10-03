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

from tools.cli.local_sources.contracts import validate_local_source_manifest
from tools.cli.local_sources.locations import validate_local_sources_root

from .locations import validate_client_root
from .materialize import (
    install_stable_launchers,
    stable_launchers_are_current,
)
from .storage import json_hash, read_json, utc_now


COMMANDS = (
    "factortester",
    "factortester-manager",
)
REGISTERED_SKILL_NAME = "factortester-research-skill"
_SKILL_RELATIVE = Path("skills") / REGISTERED_SKILL_NAME / "SKILL.md"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
Checkpoint = Callable[[str], None]


def activate_bundled_runtime(
    bundle_resources: Path,
    client_root: Path,
    *,
    checkpoint: Checkpoint | None = None,
    local_skill_root: Path | None = None,
    local_source_root: Path | None = None,
) -> dict[str, Any]:
    """Install once, then atomically select one bundle-owned runtime.

    This function is deliberately local-only. It reads one bundle receipt,
    copies the verified client/operator launchers into a versioned directory, and changes
    the current pointer only after the directory is durable.
    """
    root = validate_client_root(client_root)
    root.mkdir(parents=True, exist_ok=True)
    with _activation_lock(root):
        return _activate_locked(
            bundle_resources.expanduser().resolve(),
            root,
            checkpoint=checkpoint,
            local_skill_root=(
                local_skill_root.expanduser()
                if local_skill_root is not None
                else root / "agent-skills"
            ),
            local_source_root=validate_local_sources_root(
                local_source_root if local_source_root is not None
                else root / "sources"
            ),
        )


def _activate_locked(
    resources: Path,
    root: Path,
    *,
    checkpoint: Checkpoint | None,
    local_skill_root: Path,
    local_source_root: Path,
) -> dict[str, Any]:
    bundle_receipt = _validated_bundle_receipt(resources)
    _validate_managed_source_destinations(resources, local_source_root)
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
            return _finish_activation(
                root, version, activated=False, receipt=existing,
                resources=resources, local_skill_root=local_skill_root,
                local_source_root=local_source_root,
            )
        install_stable_launchers(root)
        if pointer_is_current:
            return _finish_activation(
                root, version, activated=True, receipt=existing,
                resources=resources, local_skill_root=local_skill_root,
                local_source_root=local_source_root,
            )
        _checkpoint(checkpoint, "before_pointer")
        _write_pointer(root, version, receipt_hash)
        install_stable_launchers(root)
        return _finish_activation(
            root, version, activated=True, receipt=existing,
            resources=resources, local_skill_root=local_skill_root,
            local_source_root=local_source_root,
        )

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
        _checkpoint(checkpoint, "before_pointer")
        _write_pointer(root, version, receipt_hash)
        install_stable_launchers(root)
        return _finish_activation(
            root, version, activated=True, receipt=receipt,
            resources=resources, local_skill_root=local_skill_root,
            local_source_root=local_source_root,
        )
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
    skill_expected = str(files.get(_SKILL_RELATIVE.as_posix()) or "")
    if not _SHA256.fullmatch(skill_expected):
        raise ValueError("bundle runtime registered Skill hash is invalid")
    skill_source = resources / _SKILL_RELATIVE
    if (
        skill_source.is_symlink()
        or not skill_source.is_file()
        or _file_hash(skill_source) != skill_expected
    ):
        raise ValueError("bundle runtime registered Skill is corrupt")
    _validate_managed_sources(resources, files)
    return receipt


def _validate_managed_sources(
    resources: Path,
    files: dict[str, Any],
) -> None:
    source_root = resources / "sources"
    if not source_root.exists():
        return
    manifests = sorted(source_root.glob("*/source.json"))
    if not manifests:
        raise ValueError("bundle runtime managed sources are missing")
    for manifest_path in manifests:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("bundle runtime source manifest is invalid")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("bundle runtime source manifest is invalid") from error
        validate_local_source_manifest(manifest)
        source_dir = manifest_path.parent
        for path in sorted(source_dir.rglob("*")):
            if _is_generated_source_path(path.relative_to(source_dir)):
                raise ValueError(
                    "bundle runtime managed source contains generated cache"
                )
            if path.is_symlink():
                raise ValueError("bundle runtime managed source contains a symlink")
            if not path.is_file():
                continue
            relative = path.relative_to(resources).as_posix()
            expected = str(files.get(relative) or "")
            if not _SHA256.fullmatch(expected) or _file_hash(path) != expected:
                raise ValueError(f"bundle runtime managed source is corrupt: {relative}")


def _is_generated_source_path(relative: Path) -> bool:
    return any(part == "__pycache__" for part in relative.parts) or any(
        part in {".DS_Store"} or part.startswith("._")
        or part.endswith((".pyc", ".pyo"))
        for part in relative.parts
    )


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
    if prefix.startswith(b"#!"):
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


def _finish_activation(
    root: Path,
    version: str,
    *,
    activated: bool,
    receipt: dict[str, Any],
    resources: Path,
    local_skill_root: Path,
    local_source_root: Path,
) -> dict[str, Any]:
    """Remove superseded runtimes only after the new pointer is durable."""
    _install_registered_skill(resources, local_skill_root)
    _install_managed_sources(resources, local_source_root)
    _prune_installed_versions(root, keep=version)
    shutil.rmtree(root / "release-runtime", ignore_errors=True)
    return _result(
        root, version, activated=activated, receipt=receipt,
    )


def _install_managed_sources(resources: Path, destination_root: Path) -> None:
    source_root = resources / "sources"
    if not source_root.is_dir():
        return
    destination_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(path for path in source_root.iterdir() if path.is_dir()):
        manifest = json.loads((source / "source.json").read_text(encoding="utf-8"))
        descriptor = validate_local_source_manifest(manifest)
        destination = destination_root / descriptor.source_id
        _validate_managed_source_destination(destination)
        if destination.exists():
            if _directory_hash(destination) == _directory_hash(source):
                continue
        staging = destination_root / f".{descriptor.source_id}.staging-{uuid.uuid4().hex}"
        backup = destination_root / f".{descriptor.source_id}.previous-{uuid.uuid4().hex}"
        try:
            shutil.copytree(source, staging)
            if destination.exists():
                os.replace(destination, backup)
            os.replace(staging, destination)
            _fsync_directory(destination_root)
            shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise


def _validate_managed_source_destinations(
    resources: Path,
    destination_root: Path,
) -> None:
    """Reject ownership conflicts before selecting a new runtime pointer."""
    if not (resources / "sources").is_dir():
        return
    for source in sorted(
        path for path in (resources / "sources").iterdir() if path.is_dir()
    ):
        manifest = json.loads((source / "source.json").read_text(encoding="utf-8"))
        descriptor = validate_local_source_manifest(manifest)
        _validate_managed_source_destination(
            destination_root / descriptor.source_id
        )


def _validate_managed_source_destination(destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError("managed source destination cannot be a symlink")
    if not destination.exists():
        return
    existing_manifest = destination / "source.json"
    try:
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("managed source destination is not replaceable") from error
    if existing.get("managed_by") != "factortester-client":
        raise ValueError("managed source destination belongs to the user")


def _directory_hash(root: Path) -> str:
    digest = sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _install_registered_skill(resources: Path, local_skill_root: Path) -> None:
    source = resources / _SKILL_RELATIVE
    destination = local_skill_root / REGISTERED_SKILL_NAME / "SKILL.md"
    if destination.is_file() and _file_hash(destination) == _file_hash(source):
        return
    if destination.parent.is_symlink():
        raise ValueError("registered Skill directory cannot be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".SKILL.md.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _prune_installed_versions(root: Path, *, keep: str) -> None:
    releases = root / "releases"
    if not releases.is_dir():
        return
    for candidate in releases.iterdir():
        if candidate.name == keep:
            continue
        if candidate.is_dir() and not candidate.is_symlink():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()
    _fsync_directory(releases)
