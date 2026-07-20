"""Bounded download and verification of one signed release asset."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from .adapters.archive import install_adapter_archive
from .contracts import ReleaseAsset


def install_asset(
    asset: ReleaseAsset,
    staging: Path,
    *,
    allow_file_urls: bool,
) -> dict[str, Any]:
    parsed = urlparse(asset.url)
    if parsed.scheme == "file" and not allow_file_urls:
        raise ValueError("file release asset URLs are test-only")
    target = staging / "artifacts" / asset.filename
    target.parent.mkdir(exist_ok=True)
    size, observed = _download_with_retry(asset, target, parsed.scheme)
    if size != asset.size:
        raise ValueError(f"release asset size mismatch: {asset.asset_id}")
    if observed != asset.sha256:
        raise ValueError(f"release asset checksum mismatch: {asset.asset_id}")
    receipt = {
        "id": asset.asset_id,
        "kind": asset.kind,
        "filename": asset.filename,
        "sha256": observed,
        "size": size,
    }
    if asset.kind == "adapter-archive":
        contract = install_adapter_archive(target, staging / "adapters")
        receipt["adapter"] = {
            "adapter_id": contract.adapter_id,
            "version": contract.version,
            "path": f"adapters/{contract.adapter_id}",
        }
    return receipt


def _download_with_retry(
    asset: ReleaseAsset,
    target: Path,
    initial_scheme: str,
) -> tuple[int, str]:
    for attempt in range(3):
        try:
            return _download_once(asset, target, initial_scheme)
        except OSError:
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(0.25 * (attempt + 1))
    raise AssertionError("unreachable")


def _download_once(
    asset: ReleaseAsset,
    target: Path,
    initial_scheme: str,
) -> tuple[int, str]:
    digest = sha256()
    size = 0
    with urlopen(asset.url, timeout=60) as source, target.open("wb") as out:
        final_scheme = urlparse(source.geturl()).scheme
        if initial_scheme == "https" and final_scheme != "https":
            raise ValueError("release asset redirected away from https")
        while chunk := source.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if size > asset.size:
                raise ValueError(
                    f"release asset size mismatch: {asset.asset_id}"
                )
    return size, digest.hexdigest()
