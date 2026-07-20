from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile

from script.release import assets as release_assets
from script.release.assets import (
    build_app_archive,
    build_installer_dmg,
    embed_client_runtime,
)
from script.release import build as release_build
from script.release.build import build_release
from script.release.manifest import _kind, create_manifest
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


def test_manifest_accepts_current_and_legacy_app_archive_names() -> None:
    assert _kind("FTClient.zip") == "macos-app"
    assert _kind("FactorTester-Client.zip") == "macos-app"


def test_release_builder_exposes_only_one_dmg(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    app = (
        repo
        / "apple/build/Build/Products/Release/FTClient.app"
    )
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_text("<plist/>")
    monkeypatch.setattr(release_build, "REPO", repo)

    def fake_embed(repo, app, *, version, source_revision):
        receipt = app / "Contents/Resources/FactorTester/bundle-receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("{}")
        return receipt

    def fake_dmg(app, output):
        assert (
            app
            / "Contents/Resources/FactorTester/bundle-receipt.json"
        ).is_file()
        output.write_bytes(b"dmg")
        return output

    monkeypatch.setattr(release_build, "embed_client_runtime", fake_embed)
    monkeypatch.setattr(release_build, "build_installer_dmg", fake_dmg)

    output = tmp_path / "release"
    result = build_release(
        version="0.2.0",
        source_revision="a" * 40,
        output=output,
    )

    assert result == output / "FactorTester-Client.dmg"
    assert [path.name for path in output.iterdir()] == [
        "FactorTester-Client.dmg"
    ]


def test_embedded_runtime_writes_internal_hash_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    adapter_builder = repo / "client-adapters/vibe-trading/build_archive.py"
    adapter_builder.parent.mkdir(parents=True)
    adapter_builder.write_text("")
    app = tmp_path / "FTClient.app"
    (app / "Contents/Resources").mkdir(parents=True)

    class FakeEnvironment:
        def __init__(self, **kwargs):
            pass

        def create(self, path):
            (path / "bin").mkdir(parents=True)
            (path / "bin/python").write_text("")
            (path / "bin/pyinstaller").write_text("")

    def fake_run(command, **kwargs):
        if "pyinstaller" in Path(command[0]).name:
            destination = Path(command[command.index("--distpath") + 1])
            destination.mkdir()
            runtime = destination / "factortester"
            runtime.write_bytes(b"runtime")
            runtime.chmod(0o755)
        elif command[-2:] and str(command[-2]).endswith("build_archive.py"):
            Path(command[-1]).write_bytes(b"adapter")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(release_assets.venv, "EnvBuilder", FakeEnvironment)
    monkeypatch.setattr(release_assets.subprocess, "run", fake_run)

    receipt = embed_client_runtime(
        repo,
        app,
        version="0.2.0",
        source_revision="b" * 40,
    )

    body = receipt.read_text()
    assert '"version":"0.2.0"' in body
    assert '"bin/factortester"' in body
    assert '"bin/cli-anything-factortester-research"' in body
    assert '"adapters/vibe-trading-adapter.zip"' in body


def test_app_archive_is_deterministic_and_preserves_executable(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FTClient.app"
    binary = app / "Contents" / "MacOS" / "FTClient"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    binary.chmod(0o755)
    (app / "Contents" / "Info.plist").write_text("<plist/>")
    first = build_app_archive(app, tmp_path / "first.zip")
    second = build_app_archive(app, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        mode = archive.getinfo(
            "FTClient.app/Contents/MacOS/FTClient"
        ).external_attr >> 16
    assert mode & 0o111
    installed = install_macos_app(first, tmp_path / "installed")
    installed_binary = tmp_path / "installed" / installed["name"]
    assert (
        installed_binary / "Contents/MacOS/FTClient"
    ).stat().st_mode & 0o111


def test_installer_dmg_contains_app_and_applications_link(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FTClient.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_text("<plist/>")
    image = build_installer_dmg(
        app,
        tmp_path / "FactorTester-Client.dmg",
    )
    assert image.is_file()
    mount = tmp_path / "mount"
    mount.mkdir()
    subprocess.run(
        [
            "hdiutil",
            "attach",
            "-nobrowse",
            "-readonly",
            "-mountpoint",
            str(mount),
            str(image),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        assert (mount / "FTClient.app").is_dir()
        assert (mount / "Applications").is_symlink()
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount)],
            check=True,
            capture_output=True,
            text=True,
        )
