from __future__ import annotations

import json
import plistlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.release import assets as release_assets
from scripts.release import build as release_build
from scripts.release import embed_runtime as runtime_refresh
from scripts.release.assets import (
    build_app_archive,
    build_installer_dmg,
    embed_client_runtime,
)
from scripts.release.build import build_release, validate_embedded_sparkle_key
from scripts.release.manifest import _kind, create_manifest
from scripts.release.source_checkout import clean_worktree
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


def test_xcode_release_product_is_hidden_then_unregistered_and_removed(
    tmp_path: Path, monkeypatch,
) -> None:
    build_root = tmp_path / "DerivedData"
    release_build.prepare_xcode_build_root(build_root)
    assert (build_root / ".metadata_never_index").is_file()

    app = build_root / "Build/Products/Release/FTClient.app"
    app.mkdir(parents=True)
    lsregister = tmp_path / "lsregister"
    lsregister.write_text("", encoding="utf-8")
    monkeypatch.setattr(release_build, "_LSREGISTER", lsregister)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        release_build.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    release_build.discard_xcode_app(app)

    assert commands == [[str(lsregister), "-u", str(app)]]
    assert not app.exists()


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


def test_release_builder_discovers_full_xcode_when_select_points_to_tools(
    tmp_path: Path,
    monkeypatch,
) -> None:
    developer = tmp_path / "Xcode.app/Contents/Developer"
    (developer / "usr/bin").mkdir(parents=True)
    (developer / "usr/bin/xcodebuild").write_text("", encoding="utf-8")
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    monkeypatch.setattr(
        release_build.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "/Library/Developer/CommandLineTools\n",
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(release_build.subprocess, "run", run)
    real_path = Path
    monkeypatch.setattr(
        release_build,
        "Path",
        lambda value: (
            developer
            if value == "/Applications/Xcode.app/Contents/Developer"
            else real_path(value)
        ),
    )

    result = release_build.xcodebuild_environment()

    assert result["DEVELOPER_DIR"] == str(developer)
    assert calls[0][0][-1] == "-version"


def test_release_builder_rejects_missing_sparkle_public_key(tmp_path: Path) -> None:
    app = tmp_path / "FTClient.app"
    info = app / "Contents"
    info.mkdir(parents=True)
    (info / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleIdentifier": "com.example.FTClient"})
    )
    with pytest.raises(ValueError, match="empty SUPublicEDKey"):
        validate_embedded_sparkle_key(app)


def test_release_builder_checks_the_expected_sparkle_public_key(
    tmp_path: Path,
) -> None:
    app = tmp_path / "FTClient.app"
    info = app / "Contents"
    info.mkdir(parents=True)
    (info / "Info.plist").write_bytes(
        plistlib.dumps({"SUPublicEDKey": "trusted-key"})
    )
    validate_embedded_sparkle_key(app, expected="trusted-key")
    with pytest.raises(ValueError, match="different SUPublicEDKey"):
        validate_embedded_sparkle_key(app, expected="other-key")


def test_local_build_script_uses_installed_app_identity() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts/build_and_run.sh"
    ).read_text(encoding="utf-8")
    assert 'APP_NAME="FTClient"' in source
    assert 'APP_NAME="FactorTester-Client"' not in source
    assert "cleanup_stale_debug_artifacts" in source
    assert "FactorTester-Client-*" in source
    assert "FTCLIENT_SKIP_DEBUG_CLEANUP" in source
    for contract in (
        "CFBundleIdentifier", "CFBundleShortVersionString",
        "CFBundleVersion", "bundle_hash", "bundle-receipt.json",
        'receipt["files"]["bin/factortester"]',
        'receipt["files"]["bin/factortester-manager"]',
        'receipt["files"]["bin/factortester-report-renderer"]',
    ):
        assert contract in source
    assert "--install|install" in source
    assert "scripts.release.embed_runtime" in source
    assert "FTCLIENT_PYTHON" in source
    assert "FTCLIENT_MARKETING_VERSION" in source
    assert "FTCLIENT_BUILD_NUMBER" in source
    assert "refusing to install an older client build" in source
    assert "FactorTester-Client.entitlements" in source
    assert "--entitlements" in source
    assert "sys.version_info >= (3, 11)" in source


def test_local_runtime_refresh_reuses_exact_revision_and_rebuilds_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = tmp_path / "FTClient.app"
    resources = app / "Contents/Resources/FactorTester"
    cli = resources / "bin/factortester"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"old")
    manager_cli = resources / "bin/factortester-manager"
    manager_cli.write_bytes(b"old")
    research_cli = resources / "bin/cli-anything-factortester-research"
    research_cli.write_bytes(b"old")
    report_renderer = resources / "bin/factortester-report-renderer"
    report_renderer.write_bytes(b"old")
    receipt = resources / "bundle-receipt.json"
    receipt.write_text(json.dumps({
        "version": "bundle-1-r" + "a" * 40,
        "source_revision": "a" * 40,
    }))
    calls = []

    def embed(repo, target, *, version, source_revision):
        calls.append((repo, target, version, source_revision))
        cli.write_bytes(b"new")
        manager_cli.write_bytes(b"new")
        research_cli.write_bytes(b"new")
        report_renderer.write_bytes(b"new")
        return receipt

    monkeypatch.setattr(runtime_refresh, "embed_client_runtime", embed)
    assert runtime_refresh.ensure_client_runtime(
        app=app,
        version="bundle-1-r" + "a" * 40,
        source_revision="a" * 40,
    ) is False
    assert calls == []

    assert runtime_refresh.ensure_client_runtime(
        app=app,
        version="bundle-1-r" + "b" * 40,
        source_revision="b" * 40,
    ) is True
    assert calls[0][1:] == (
        app,
        "bundle-1-r" + "b" * 40,
        "b" * 40,
    )


def test_local_runtime_refresh_rejects_short_revision_before_fast_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="full 40-character Git revision"):
        runtime_refresh.ensure_client_runtime(
            app=tmp_path / "FTClient.app",
            version="bundle-1-rshort",
            source_revision="fb35e13c",
        )


def test_local_build_script_requires_stable_signature_for_privacy_grants() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts/build_and_run.sh"
    ).read_text(encoding="utf-8")

    assert 'SIGNING_IDENTITY="${FTCLIENT_SIGNING_IDENTITY:-FTClient Beta Release}"' in source
    assert 'codesign --force --deep --sign "$SIGNING_IDENTITY"' in source
    assert 'codesign --verify --deep --strict "$APP_BUNDLE"' in source
    assert 'designated_requirement "$APP_BUNDLE"' in source
    assert 'require_same_identity "$APP_BUNDLE" "$INSTALLED_APP"' in source
    assert 'signature identity changed; refusing to replace' in source
    assert "privacy grants" in source


def test_xcode_macos_target_uses_the_same_stable_signing_identity() -> None:
    project = (
        Path(__file__).resolve().parents[2] / "apple/project.yml"
    ).read_text(encoding="utf-8")
    macos = project.split("FactorTester-Client-macOS:", 1)[1].split(
        "FactorTester-ClientTests:", 1
    )[0]

    assert "CODE_SIGN_STYLE: Manual" in macos
    assert "CODE_SIGN_IDENTITY: FTClient Beta Release" in macos
    assert "ENABLE_DEBUG_DYLIB: NO" in macos
    assert "Debug:\n          # XCTest is injected" in macos
    assert "ENABLE_HARDENED_RUNTIME: NO" in macos
    assert "Release:\n          ENABLE_HARDENED_RUNTIME: YES" in macos

    unit_tests = project.split("FactorTester-ClientTests:", 1)[1].split(
        "FactorTester-ClientUITests:", 1
    )[0]
    ui_tests = project.split("FactorTester-ClientUITests:", 1)[1].split(
        "schemes:", 1
    )[0]
    for test_target in (unit_tests, ui_tests):
        assert "CODE_SIGN_STYLE: Manual" in test_target
        assert "CODE_SIGN_IDENTITY: FTClient Beta Release" in test_target
        assert 'CODE_SIGN_IDENTITY: "-"' not in test_target
    schemes = project.split("schemes:", 1)[1]
    unit_scheme = schemes.split("FactorTester-Client-UI:", 1)[0]
    ui_scheme = schemes.split("FactorTester-Client-UI:", 1)[1]
    assert "- FactorTester-ClientTests" in unit_scheme
    assert "- FactorTester-ClientUITests" not in unit_scheme
    assert "- FactorTester-ClientUITests" in ui_scheme


def test_report_tree_reuses_the_persisted_workspace_access_scope() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "apple/Sources/Features/Profiles/ResearchReport/Tree/ResearchReportTreeNodeLoader.swift"
    ).read_text(encoding="utf-8")

    assert "PersonalWorkspaceAccessStore.withAccess(to: url)" in source
    assert "Data(contentsOf: url, options: .mappedIfSafe)" in source


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
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "4",
            "SUPublicEDKey": "test-key",
        }, stream)
    monkeypatch.setattr(release_build, "REPO", repo)
    monkeypatch.setattr(
        release_build, "_validate_source_checkout", lambda *_args: None
    )

    def fake_embed(repo, app, *, version, source_revision):
        assert version == "bundle-b4-r" + "a" * 40
        receipt = app / "Contents/Resources/FactorTester/bundle-receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text("{}")
        return receipt

    signed = False

    def fake_sign(app, signing_identity):
        nonlocal signed
        assert signing_identity == "FTClient Beta Release"
        signed = True

    def fake_dmg(app, output):
        assert signed is True
        assert (
            app
            / "Contents/Resources/FactorTester/bundle-receipt.json"
        ).is_file()
        output.write_bytes(b"dmg")
        return output

    monkeypatch.setattr(release_build, "embed_client_runtime", fake_embed)
    monkeypatch.setattr(release_build, "_sign_embedded_app", fake_sign)
    monkeypatch.setattr(release_build, "build_installer_dmg", fake_dmg)

    output = tmp_path / "release"
    result = build_release(
        version="0.2.0",
        source_revision="a" * 40,
        output=output,
        signing_identity="FTClient Beta Release",
    )

    assert result == output / "FactorTester-Client.dmg"
    assert [path.name for path in output.iterdir()] == [
        "FactorTester-Client.dmg"
    ]


def test_embedded_app_is_resigned_and_verified_before_packaging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = tmp_path / "FTClient.app"
    commands: list[list[str]] = []

    def record(command, **kwargs):
        commands.append(command)
        if command[1:4] == ["-d", "--entitlements", ":-"]:
            return subprocess.CompletedProcess(
                command,
                0,
                b"<key>com.apple.security.cs.disable-library-validation</key>",
                b"",
            )
        detail = (
            'designated => identifier "com.gtht.client" and anchor trusted\n'
            if command[1:3] == ["-d", "-r-"] else ""
        )
        return subprocess.CompletedProcess(command, 0, "", detail)

    monkeypatch.setattr(release_build.subprocess, "run", record)

    release_build._sign_embedded_app(app, "FTClient Beta Release")

    assert commands == [
        [
            "codesign", "--force", "--sign",
            "FTClient Beta Release", "--options", "runtime",
            "--timestamp=none", "--entitlements",
            str(
                release_build.REPO
                / "apple/Resources/macOS/FactorTester-Client.entitlements"
            ),
            str(app),
        ],
        [
            "codesign", "--verify", "--strict",
            "--all-architectures", str(app),
        ],
        ["codesign", "-d", "--entitlements", ":-", str(app)],
        ["codesign", "-d", "-r-", str(app)],
    ]


def test_release_builder_rejects_ephemeral_adhoc_signature(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="stable signing identity"):
        release_build._sign_embedded_app(tmp_path / "FTClient.app", "-")


def test_release_builder_rejects_cdhash_designated_requirement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def record(command, **kwargs):
        if command[1:4] == ["-d", "--entitlements", ":-"]:
            return subprocess.CompletedProcess(
                command,
                0,
                b"<key>com.apple.security.cs.disable-library-validation</key>",
                b"",
            )
        detail = (
            'designated => cdhash H"0123456789abcdef"\n'
            if command[1:3] == ["-d", "-r-"] else ""
        )
        return subprocess.CompletedProcess(command, 0, "", detail)

    monkeypatch.setattr(release_build.subprocess, "run", record)
    with pytest.raises(ValueError, match="stable designated requirement"):
        release_build._sign_embedded_app(
            tmp_path / "FTClient.app", "FTClient Beta Release"
        )


def test_release_builder_rejects_app_version_or_revision_reuse_inputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    app = repo / "apple/build/Build/Products/Release/FTClient.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "4",
            "SUPublicEDKey": "test-key",
        }, stream)
    monkeypatch.setattr(release_build, "REPO", repo)
    monkeypatch.setattr(
        release_build, "_validate_source_checkout", lambda *_args: None
    )

    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        build_release(
            version="0.2.0",
            source_revision="short",
            output=tmp_path / "bad-revision",
        )
    with pytest.raises(ValueError, match="does not match"):
        build_release(
            version="0.2.1",
            source_revision="a" * 40,
            output=tmp_path / "bad-version",
        )


def test_release_builder_binds_revision_and_clean_client_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    revision = "a" * 40

    def clean(command, **_kwargs):
        return revision + "\n" if command[1:3] == ["rev-parse", "HEAD"] else ""

    monkeypatch.setattr(release_build.subprocess, "check_output", clean)
    release_build._validate_source_checkout(tmp_path, revision)

    with pytest.raises(ValueError, match="does not match"):
        release_build._validate_source_checkout(tmp_path, "b" * 40)

    def dirty(command, **_kwargs):
        if command[1:3] == ["rev-parse", "HEAD"]:
            return revision + "\n"
        return " M apple/Sources/App.swift\n"

    monkeypatch.setattr(release_build.subprocess, "check_output", dirty)
    with pytest.raises(ValueError, match="unpublished client changes"):
        release_build._validate_source_checkout(tmp_path, revision)


def test_clean_commit_fallback_requires_explicit_temporary_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Tests"],
        check=True,
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "base"], check=True
    )
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    (repo / "unpublished.txt").write_text("dirty\n", encoding="utf-8")

    with clean_worktree(repo, revision) as checkout:
        assert (checkout / "tracked.txt").read_text() == "base\n"
        assert not (checkout / "unpublished.txt").exists()
        observed = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        assert observed == revision

    assert (repo / "unpublished.txt").exists()


def test_embedded_runtime_writes_internal_hash_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    client_adapters_root = tmp_path / "client-adapters"
    adapter_builder = client_adapters_root / "vibe-trading/build_archive.py"
    adapter_builder.parent.mkdir(parents=True)
    adapter_builder.write_text("")
    renderer_source = repo / "tools/cli/native/report_renderer.swift"
    renderer_source.parent.mkdir(parents=True)
    renderer_source.write_text("// renderer")
    skill = repo / "skills/cli-anything-factortester-research/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: factortester-research-skill\n"
        "description: Test skill.\n---\n\n# Test\n",
        encoding="utf-8",
    )
    client_sources_root = tmp_path / "client-sources"
    tiger = client_sources_root / "Tiger"
    tiger.mkdir(parents=True)
    tiger.joinpath("source.json").write_text(
        '{"source_id":"Tiger"}\n', encoding="utf-8",
    )
    tiger.joinpath("connector.py").write_text(
        "# test connector\n", encoding="utf-8",
    )
    generated = tiger / "__pycache__/connector.cpython-314.pyc"
    generated.parent.mkdir()
    generated.write_bytes(b"generated bytecode must not ship")
    app = tmp_path / "FTClient.app"
    (app / "Contents/Resources").mkdir(parents=True)

    def fake_environment(path):
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
        elif "swiftc" in command:
            destination = Path(command[command.index("-o") + 1])
            destination.write_bytes(b"renderer")
            destination.chmod(0o755)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        release_assets, "_create_runtime_environment", fake_environment
    )
    monkeypatch.setattr(release_assets.subprocess, "run", fake_run)
    monkeypatch.setattr(
        release_assets, "validate_client_package_layout", lambda _repo: None
    )
    node = tmp_path / "node"
    node.write_bytes(b"node")
    monkeypatch.setattr(
        release_assets, "_nodejs_wheel_binary", lambda _environment: node
    )

    receipt = embed_client_runtime(
        repo,
        app,
        version="0.2.0",
        source_revision="b" * 40,
        client_sources_root=client_sources_root,
        client_adapters_root=client_adapters_root,
    )

    body = receipt.read_text()
    assert '"version":"0.2.0"' in body
    assert '"bin/factortester"' in body
    assert '"bin/factortester-manager"' in body
    assert '"bin/cli-anything-factortester-research"' in body
    assert '"bin/factortester-report-renderer"' in body
    assert '"adapters/vibe-trading-adapter.zip"' in body
    resources = app / "Contents/Resources/FactorTester"
    assert not (resources / "sources/Tiger/__pycache__").exists()
    assert not any(path.suffix == ".pyc" for path in resources.rglob("*"))


def test_frozen_publisher_creates_venv_with_host_python(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(release_assets.sys, "frozen", True, raising=False)
    monkeypatch.setenv("FTCLIENT_RELEASE_PYTHON", "/host/python3")
    monkeypatch.setattr(
        release_assets.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    environment = tmp_path / "venv"
    release_assets._create_runtime_environment(environment)

    assert calls == [
        (["/host/python3", "-m", "venv", str(environment)], {"check": True})
    ]


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
    versions = app / "Contents/Frameworks/Sparkle.framework/Versions/B"
    versions.mkdir(parents=True)
    (versions / "Sparkle").write_bytes(b"framework")
    (app / "Contents/Frameworks/Sparkle.framework/Sparkle").symlink_to(
        "Versions/B/Sparkle"
    )
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
        assert (
            mount
            / "FTClient.app/Contents/Frameworks/Sparkle.framework/Sparkle"
        ).is_symlink()
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount)],
            check=True,
            capture_output=True,
            text=True,
        )
