"""Build and inspect transport bundles for a signed client release."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import zipfile
from typing import Iterable


MAX_CLIENT_RELEASE_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_CLIENT_RELEASE_ENTRIES = 32
MAX_CLIENT_RELEASE_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_MEMBER = re.compile(r"^assets/beta/([0-9a-f]{64})\.(dmg|delta)$")
_BASE_MEMBER = re.compile(r"^bases/beta/([0-9a-f]{64})\.dmg$")
_REQUIRED_MEMBERS = frozenset({"beta.json", "beta.xml"})


def build_client_release_bundle(
    *,
    dmg: Path,
    appcast: Path,
    manifest: Path,
    output: Path,
    deltas: Iterable[Path] = (),
    bases: Iterable[Path] = (),
) -> dict[str, object]:
    """Create one bounded, path-safe ZIP bundle for a Beta publication."""
    dmg = Path(dmg).expanduser().resolve()
    appcast = Path(appcast).expanduser().resolve()
    manifest = Path(manifest).expanduser().resolve()
    for path, label in (
        (dmg, "DMG"), (appcast, "appcast"), (manifest, "manifest"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"client release {label} is unavailable")
    parsed = _manifest(manifest)
    digest = _file_sha256(dmg)
    if digest != str(parsed.get("sha256") or "").lower():
        raise ValueError("client release DMG does not match its manifest")

    members: list[tuple[str, Path]] = [
        ("beta.json", manifest),
        ("beta.xml", appcast),
        (f"assets/beta/{digest}.dmg", dmg),
    ]
    for path in deltas:
        source = Path(path).expanduser().resolve()
        name = source.name
        if not source.is_file() or source.is_symlink() or not _DIGEST.fullmatch(name[:-6]):
            raise ValueError(f"client release delta is invalid: {source}")
        members.append((f"assets/beta/{name}", source))
    for path in bases:
        source = Path(path).expanduser().resolve()
        name = source.name
        if not source.is_file() or source.is_symlink() or not _DIGEST.fullmatch(name[:-4]):
            raise ValueError(f"client release base is invalid: {source}")
        members.append((f"bases/beta/{name}", source))
    return _write_bundle(
        members,
        output=Path(output).expanduser().resolve(),
        version=str(parsed.get("version") or ""),
        build=int(parsed.get("build") or 0),
        dmg_sha256=digest,
    )


def inspect_client_release_bundle(path: Path) -> dict[str, object]:
    """Validate archive shape without extracting untrusted paths."""
    archive = Path(path).expanduser().resolve()
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("client release package is unavailable")
    if archive.stat().st_size > MAX_CLIENT_RELEASE_PACKAGE_BYTES:
        raise ValueError("client release package is too large")
    with zipfile.ZipFile(archive, "r") as bundle:
        infos = bundle.infolist()
        if not infos or len(infos) > MAX_CLIENT_RELEASE_ENTRIES:
            raise ValueError("client release package entry count is invalid")
        names: set[str] = set()
        total = 0
        for info in infos:
            name = _safe_member_name(info.filename)
            if name in names or info.is_dir():
                raise ValueError("client release package contains duplicate or directory entries")
            names.add(name)
            if info.file_size > MAX_CLIENT_RELEASE_MEMBER_BYTES:
                raise ValueError("client release package member is too large")
            total += info.file_size
            if total > MAX_CLIENT_RELEASE_PACKAGE_BYTES:
                raise ValueError("client release package expands beyond its limit")
            if name not in _REQUIRED_MEMBERS and not (
                _RELEASE_MEMBER.fullmatch(name) or _BASE_MEMBER.fullmatch(name)
            ):
                raise ValueError(f"client release package member is not allowed: {name}")
        if not _REQUIRED_MEMBERS.issubset(names):
            raise ValueError("client release package is missing release metadata")
        manifest = json.loads(bundle.read("beta.json"))
        if not isinstance(manifest, dict):
            raise ValueError("client release manifest must be an object")
        digest = str(manifest.get("sha256") or "").lower()
        if not _DIGEST.fullmatch(digest):
            raise ValueError("client release manifest DMG digest is invalid")
        dmg_name = f"assets/beta/{digest}.dmg"
        if dmg_name not in names:
            raise ValueError("client release package does not contain the manifest DMG")
        if _zip_sha256(bundle, dmg_name) != digest:
            raise ValueError("client release package DMG digest mismatch")
        return {
            "version": str(manifest.get("version") or ""),
            "build": int(manifest.get("build") or 0),
            "dmg_sha256": digest,
            "package_size_bytes": archive.stat().st_size,
            "package_sha256": _file_sha256(archive),
            "members": sorted(names),
        }


def extract_client_release_bundle(path: Path, destination: Path) -> dict[str, object]:
    """Extract a validated bundle into a fresh private directory."""
    metadata = inspect_client_release_bundle(path)
    target = Path(destination).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(Path(path).expanduser().resolve(), "r") as bundle:
            for info in bundle.infolist():
                name = _safe_member_name(info.filename)
                member = (target / name).resolve()
                if target not in member.parents:
                    raise ValueError("client release package escapes extraction root")
                member.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info, "r") as source, member.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    except BaseException:
        _remove_tree(target)
        raise
    return metadata


def _write_bundle(
    members: list[tuple[str, Path]],
    *,
    output: Path,
    version: str,
    build: int,
    dmg_sha256: str,
) -> dict[str, object]:
    if output.exists():
        raise ValueError(f"client release package already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in members]
    if len(names) != len(set(names)):
        raise ValueError("client release package contains duplicate members")
    temporary = output.with_name(f".{output.name}.staging")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True,
        ) as bundle:
            for name, source in members:
                _safe_member_name(name)
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_STORED
                bundle.write(source, arcname=name)
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    metadata = inspect_client_release_bundle(output)
    metadata.update({"version": version, "build": build, "dmg_sha256": dmg_sha256})
    return metadata


def _manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("client release manifest is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("client release manifest must be an object")
    return value


def _safe_member_name(value: str) -> str:
    name = str(value or "")
    if (
        not name or name.startswith("/") or "\\" in name
        or "\x00" in name or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("client release package member path is invalid")
    return name


def _zip_sha256(bundle: zipfile.ZipFile, name: str) -> str:
    digest = sha256()
    with bundle.open(name, "r") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "MAX_CLIENT_RELEASE_ENTRIES",
    "MAX_CLIENT_RELEASE_PACKAGE_BYTES",
    "build_client_release_bundle",
    "extract_client_release_bundle",
    "inspect_client_release_bundle",
]
