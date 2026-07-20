"""Bounded extraction and validation of a signed macOS app archive."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


MAX_APP_ENTRIES = 5_000
MAX_APP_BYTES = 512 * 1024 * 1024


def install_macos_app(archive_path: Path, destination: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_APP_ENTRIES:
            raise ValueError("macOS app archive entry count is invalid")
        if sum(item.file_size for item in entries) > MAX_APP_BYTES:
            raise ValueError("macOS app archive expanded size exceeds limit")
        for item in entries:
            _validate(item)
        roots = {PurePosixPath(item.filename).parts[0] for item in entries}
        app_roots = sorted(name for name in roots if name.endswith(".app"))
        if len(app_roots) != 1 or len(roots) != 1:
            raise ValueError("macOS app archive must contain exactly one app")
        destination.mkdir(parents=True, exist_ok=True)
        for item in entries:
            _extract(archive, item, destination)
    app = destination / app_roots[0]
    plist = app / "Contents" / "Info.plist"
    executable_root = app / "Contents" / "MacOS"
    executables = [
        path for path in executable_root.iterdir()
        if path.is_file() and os.access(path, os.X_OK)
    ] if executable_root.is_dir() else []
    if not plist.is_file() or not executables:
        raise ValueError("materialized macOS application is incomplete")
    return {"path": f"applications/{app.name}", "name": app.name}


def _validate(item: zipfile.ZipInfo) -> None:
    path = PurePosixPath(item.filename)
    mode = item.external_attr >> 16
    if (
        not item.filename
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in item.filename
        or stat.S_IFMT(mode) == stat.S_IFLNK
    ):
        raise ValueError(f"unsafe macOS app archive path: {item.filename}")


def _extract(
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
        shutil.copyfileobj(source, output, length=1024 * 1024)
    permissions = (item.external_attr >> 16) & 0o777
    target.chmod(permissions or 0o600)
