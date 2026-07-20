from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile

from script.release.assets import build_app_archive
from script.release.manifest import create_manifest
from tools.cli.release.contracts import validate_release_manifest


def _keys(root: Path) -> tuple[Path, Path]:
    private = root / "private.pem"
    public = root / "public.pem"
    subprocess.run(
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout",
         "-out", str(private)],
        check=True,
    )
    subprocess.run(
        ["openssl", "ec", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def test_manifest_builder_signs_explicit_assets(tmp_path: Path) -> None:
    private, public = _keys(tmp_path)
    wheel = tmp_path / "factortester-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    manifest = create_manifest(
        version="0.1.0",
        revision="a" * 40,
        base_url="https://example.test/download",
        assets=[wheel],
        private_key=private,
        public_key=public,
    )

    release = validate_release_manifest(manifest, public_key=public)
    assert release.assets[0].url.endswith(wheel.name)
    assert release.assets[0].size == 5


def test_app_archive_is_deterministic_and_preserves_executable(
    tmp_path: Path,
) -> None:
    app = tmp_path / "GTHTClient.app"
    binary = app / "Contents" / "MacOS" / "GTHTClient"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    binary.chmod(0o755)
    (app / "Contents" / "Info.plist").write_text("<plist/>")
    first = build_app_archive(app, tmp_path / "first.zip")
    second = build_app_archive(app, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        mode = archive.getinfo(
            "GTHTClient.app/Contents/MacOS/GTHTClient"
        ).external_attr >> 16
    assert mode & 0o111
