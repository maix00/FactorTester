"""Read the signed, content-addressed desktop-local runtime release catalog."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache
from typing import Any

from tools.cli.release.signature import verify_ecdsa_sha256

_PLATFORMS = {"macos-arm64", "windows-x86_64", "linux-x86_64"}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_CATALOG = 256 * 1024
_MAX_PACKAGE = 4 * 1024 * 1024 * 1024
DESKTOP_LOCAL_NODE_DOWNLOAD_ROLE = "desktop_local_node:download"


def canonical_unsigned_catalog(value: dict[str, Any]) -> bytes:
    unsigned = dict(value)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=16)
def _validated_catalog(catalog_path: str, catalog_mtime_ns: int, catalog_size: int,
                       catalog_inode: int, catalog_ctime_ns: int, public_key_path: str,
                       public_key_mtime_ns: int, public_key_inode: int,
                       public_key_ctime_ns: int) -> dict[str, Any]:
    del (catalog_mtime_ns, catalog_size, catalog_inode, catalog_ctime_ns,
         public_key_mtime_ns, public_key_inode, public_key_ctime_ns)
    path = Path(catalog_path)
    raw = path.read_bytes()
    if len(raw) > _MAX_CATALOG:
        raise ValueError("local node catalog exceeds its size limit")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("local node catalog schema is invalid")
    if set(value) != {"schema_version", "packages", "signature"}:
        raise ValueError("local node catalog fields are invalid")
    signature = value.get("signature")
    if not isinstance(signature, dict) or set(signature) != {"algorithm", "key_id", "value"}:
        raise ValueError("local node catalog signature is invalid")
    public_key = Path(public_key_path)
    key_id = hashlib.sha256(public_key.read_bytes()).hexdigest()
    if signature.get("algorithm") != "ecdsa-sha256" or signature.get("key_id") != key_id:
        raise ValueError("local node catalog key is not trusted")
    verify_ecdsa_sha256(canonical_unsigned_catalog(value), str(signature.get("value") or ""), public_key=public_key)
    packages = value.get("packages")
    if not isinstance(packages, list) or len(packages) > 16:
        raise ValueError("local node catalog package list is invalid")
    seen: set[str] = set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"platform", "version", "sha256", "size_bytes"}:
            raise ValueError("local node package metadata is invalid")
        platform = str(package.get("platform") or "")
        digest = str(package.get("sha256") or "")
        version = str(package.get("version") or "")
        size = package.get("size_bytes")
        if (platform not in _PLATFORMS or platform in seen or not version or len(version) > 128
                or not _DIGEST.fullmatch(digest) or type(size) is not int
                or not 1 <= size <= _MAX_PACKAGE):
            raise ValueError("local node package metadata is invalid")
        seen.add(platform)
    return value


class LocalNodeReleaseCatalog:
    """Verify signatures once per catalog revision and stream bounded assets."""
    def __init__(self, root: Path, public_key: Path):
        self.root = Path(root).resolve()
        self.public_key = Path(public_key).resolve()

    def _catalog(self) -> dict[str, Any] | None:
        catalog_root = self.root / "local-node"
        path = catalog_root / "index.json"
        try:
            if catalog_root.is_symlink():
                raise ValueError("local node catalog directory is invalid")
            stat = path.lstat()
            key_stat = self.public_key.stat()
        except FileNotFoundError:
            return None
        if not path.is_file() or path.is_symlink() or stat.st_size > _MAX_CATALOG:
            raise ValueError("local node catalog file is invalid")
        return _validated_catalog(
            str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino,
            stat.st_ctime_ns, str(self.public_key), key_stat.st_mtime_ns,
            key_stat.st_ino, key_stat.st_ctime_ns,
        )

    def package(self, platform: str) -> dict[str, Any] | None:
        if platform not in _PLATFORMS:
            raise ValueError("unsupported local node platform")
        catalog = self._catalog()
        if catalog is None:
            return None
        return next((item for item in catalog["packages"] if item["platform"] == platform), None)

    def asset(self, platform: str, digest: str) -> Path:
        if platform not in _PLATFORMS or not _DIGEST.fullmatch(digest):
            raise ValueError("local node asset identity is invalid")
        package = self.package(platform)
        if package is None or package["sha256"] != digest:
            raise FileNotFoundError("local node package is not published")
        asset_root = self.root / "assets"
        local_root = asset_root / "local-node"
        platform_root = local_root / platform
        if any(directory.is_symlink() for directory in (asset_root, local_root, platform_root)):
            raise FileNotFoundError("local node package directory is unavailable")
        path = platform_root / f"{digest}.tar.zst"
        resolved = path.resolve(strict=True)
        expected = platform_root.resolve()
        info = path.lstat()
        if resolved.parent != expected or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("local node package is unavailable")
        if info.st_size != package["size_bytes"]:
            raise ValueError("local node package size does not match its signed catalog")
        _verify_asset(
            str(resolved), info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, digest,
        )
        return resolved


@lru_cache(maxsize=32)
def _verify_asset(path: str, device: int, inode: int, size: int,
                  mtime_ns: int, ctime_ns: int, expected_digest: str) -> None:
    """Hash each immutable package revision once, with a bounded hot cache."""
    del device, inode, size, mtime_ns, ctime_ns
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != expected_digest:
        raise ValueError("local node package digest does not match its signed catalog")
