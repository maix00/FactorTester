from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from tools.cli.release.app_archive import install_macos_app


def _app_archive(path: Path, *, unsafe: str = "") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("GTHTClient.app/Contents/Info.plist", "<plist/>")
        executable = zipfile.ZipInfo(
            "GTHTClient.app/Contents/MacOS/GTHTClient"
        )
        executable.external_attr = 0o100755 << 16
        archive.writestr(executable, "#!/bin/sh\nexit 0\n")
        if unsafe:
            archive.writestr(unsafe, "escape")
    return path


def test_signed_macos_app_is_materialized_inside_version_root(
    tmp_path: Path,
) -> None:
    result = install_macos_app(
        _app_archive(tmp_path / "client.zip"),
        tmp_path / "applications",
    )
    assert result == {
        "path": "applications/GTHTClient.app",
        "name": "GTHTClient.app",
    }
    assert (
        tmp_path / result["path"] / "Contents" / "MacOS" / "GTHTClient"
    ).stat().st_mode & 0o111


def test_macos_app_archive_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        install_macos_app(
            _app_archive(tmp_path / "unsafe.zip", unsafe="../escape"),
            tmp_path / "applications",
        )
