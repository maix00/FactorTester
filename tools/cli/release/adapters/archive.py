"""Bounded, traversal-safe extraction of a signed adapter archive."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

from .contracts import AdapterContract, validate_adapter_contract


MAX_ARCHIVE_ENTRIES = 5_000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024


def install_adapter_archive(
    archive_path: Path,
    adapters_root: Path,
) -> AdapterContract:
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("adapter archive entry count is invalid")
        if sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("adapter archive expanded size exceeds limit")
        for item in entries:
            _validate_entry(item)
        try:
            manifest = json.loads(archive.read("adapter.json"))
        except KeyError as exc:
            raise ValueError("adapter archive is missing adapter.json") from exc
        contract = validate_adapter_contract(manifest)
        destination = adapters_root / contract.adapter_id
        if destination.exists():
            raise ValueError(f"duplicate adapter archive: {contract.adapter_id}")
        destination.mkdir(parents=True)
        try:
            for item in entries:
                _extract_entry(archive, item, destination)
        except Exception:
            import shutil
            shutil.rmtree(destination, ignore_errors=True)
            raise
    return contract


def _validate_entry(item: zipfile.ZipInfo) -> None:
    path = PurePosixPath(item.filename)
    if (
        not item.filename
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in item.filename
    ):
        raise ValueError(f"unsafe adapter archive path: {item.filename}")
    mode = item.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise ValueError(f"adapter archive symlink is forbidden: {item.filename}")


def _extract_entry(
    archive: zipfile.ZipFile,
    item: zipfile.ZipInfo,
    destination: Path,
) -> None:
    relative = PurePosixPath(item.filename)
    target = destination.joinpath(*relative.parts)
    if item.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(item) as source, target.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    permissions = (item.external_attr >> 16) & 0o777
    os.chmod(target, permissions or 0o600)
