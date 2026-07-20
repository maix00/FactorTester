from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile

from script.release.assets import build_app_archive, build_installer_dmg
from script.release.build import build_release
from script.release.manifest import create_manifest
from tools.cli.release.app_archive import install_macos_app
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


def test_release_builder_requires_public_source_revision() -> None:
    assert "source_revision" in build_release.__annotations__


def test_app_archive_is_deterministic_and_preserves_executable(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FactorTester-Client.app"
    binary = app / "Contents" / "MacOS" / "FactorTester-Client"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    binary.chmod(0o755)
    (app / "Contents" / "Info.plist").write_text("<plist/>")
    first = build_app_archive(app, tmp_path / "first.zip")
    second = build_app_archive(app, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        mode = archive.getinfo(
            "FactorTester-Client.app/Contents/MacOS/FactorTester-Client"
        ).external_attr >> 16
    assert mode & 0o111
    installed = install_macos_app(first, tmp_path / "installed")
    installed_binary = tmp_path / "installed" / installed["name"]
    assert (
        installed_binary / "Contents/MacOS/FactorTester-Client"
    ).stat().st_mode & 0o111


def test_installer_dmg_contains_app_and_applications_link(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FactorTester-Client.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_text("<plist/>")
    image = build_installer_dmg(
        app,
        tmp_path / "FactorTester-Client.dmg",
    )
    assert image.is_file()
    listing = subprocess.run(
        ["hdiutil", "imageinfo", str(image)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "FactorTester-Client" in listing.stdout
