"""Bounded download and verification of one signed release asset."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

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
    digest = sha256()
    size = 0
    with urlopen(asset.url, timeout=60) as source, target.open("wb") as out:
        final_scheme = urlparse(source.geturl()).scheme
        if parsed.scheme == "https" and final_scheme != "https":
            raise ValueError("release asset redirected away from https")
        while chunk := source.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if size > asset.size:
                raise ValueError(
                    f"release asset size mismatch: {asset.asset_id}"
                )
    if size != asset.size:
        raise ValueError(f"release asset size mismatch: {asset.asset_id}")
    observed = digest.hexdigest()
    if observed != asset.sha256:
        raise ValueError(f"release asset checksum mismatch: {asset.asset_id}")
    return {
        "id": asset.asset_id,
        "kind": asset.kind,
        "filename": asset.filename,
        "sha256": observed,
        "size": size,
    }
