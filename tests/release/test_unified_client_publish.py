from __future__ import annotations

import json
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from click.testing import CliRunner

from scripts.release import publish
from tools.cli.commands.client_release import client, operator_client
from tools.cli.release import app_update_control


def _appcast(
    path: Path,
    *,
    version: str,
    build: int,
    channel: str,
    url: str,
) -> Path:
    channel_element = (
        f"<sparkle:channel>{channel}</sparkle:channel>"
        if channel == "beta" else ""
    )
    path.write_text(
        f"""<?xml version="1.0"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
<channel><item>
<sparkle:version>{build}</sparkle:version>
<sparkle:shortVersionString>{version}</sparkle:shortVersionString>
{channel_element}
<enclosure url="{url}" sparkle:edSignature="signed" />
</item></channel></rss>
""",
        encoding="utf-8",
    )
    return path


def test_beta_publishes_sparkle_and_legacy_pointers_last(
    tmp_path: Path,
) -> None:
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"release")
    digest = sha256(b"release").hexdigest()
    appcast = _appcast(
        tmp_path / "appcast.xml",
        version="1.2.3",
        build=42,
        channel="beta",
        url=f"https://factor.example/assets/beta/{digest}.dmg",
    )
    root = tmp_path / "published"
    delta = tmp_path / "delta.sha256.delta"
    delta.write_bytes(b"delta")

    publication = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
        deltas=(delta,),
    )

    assert (root / "assets/beta" / f"{digest}.dmg").is_file()
    assert (root / "beta.xml").read_bytes() == appcast.read_bytes()
    assert json.loads((root / "beta.json").read_text())["sha256"] == digest
    assert (root / "assets/beta/delta.sha256.delta").read_bytes() == b"delta"
    publication.finalize()


def test_full_beta_publish_prunes_unreachable_prior_artifacts(
    tmp_path: Path,
) -> None:
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"release")
    digest = sha256(b"release").hexdigest()
    appcast = _appcast(
        tmp_path / "appcast.xml",
        version="1.2.3",
        build=42,
        channel="beta",
        url=f"https://factor.example/assets/beta/{digest}.dmg",
    )
    root = tmp_path / "published"
    old_asset = root / "assets/beta/old.dmg"
    old_asset.parent.mkdir(parents=True, exist_ok=True)
    old_asset.write_bytes(b"old")
    old_delta = root / "assets/beta/old.delta"
    old_delta.write_bytes(b"old delta")
    old_appcast = root / "appcasts/beta/old.xml"
    old_appcast.parent.mkdir(parents=True, exist_ok=True)
    old_appcast.write_text("old", encoding="utf-8")
    old_base = root / "bases/beta/old.dmg"
    old_base.parent.mkdir(parents=True, exist_ok=True)
    old_base.write_bytes(b"old")

    publication = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
        publish_full=True,
    )
    publication.finalize()

    assert (root / "assets/beta" / f"{digest}.dmg").is_file()
    assert not old_asset.exists()
    assert not old_delta.exists()
    assert not old_appcast.exists()
    assert not old_base.exists()


def test_beta_can_publish_delta_without_current_full_archive(
    tmp_path: Path,
) -> None:
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"release")
    appcast = _appcast(
        tmp_path / "appcast.xml",
        version="1.2.3",
        build=42,
        channel="beta",
        url="https://factor.example/assets/beta/current.dmg",
    )
    root = tmp_path / "published"
    delta = tmp_path / ("a" * 64 + ".delta")
    delta.write_bytes(b"delta")
    old_asset = root / "assets/beta/old.dmg"
    old_asset.parent.mkdir(parents=True, exist_ok=True)
    old_asset.write_bytes(b"old")
    old_delta = root / "assets/beta/old.delta"
    old_delta.write_bytes(b"old delta")
    old_appcast = root / "appcasts/beta/old.xml"
    old_appcast.parent.mkdir(parents=True, exist_ok=True)
    old_appcast.write_text("old", encoding="utf-8")

    publication = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": "a" * 64},
        release_root=root,
        deltas=(delta,),
        publish_full=False,
        retain_base=True,
    )

    asset = root / "assets/beta" / f"{sha256(b'release').hexdigest()}.dmg"
    assert asset == root / "assets/beta" / f"{sha256(b'release').hexdigest()}.dmg"
    assert not asset.exists()
    assert (
        root / "bases/beta" / f"{sha256(b'release').hexdigest()}.dmg"
    ).read_bytes() == b"release"
    assert (root / "assets/beta" / delta.name).read_bytes() == b"delta"
    publication.finalize()
    assert not old_asset.exists()
    assert not old_delta.exists()
    assert not old_appcast.exists()
    assert not list(root.rglob("*.staging-*"))


def test_failed_beta_readback_can_restore_previous_channel(tmp_path: Path) -> None:
    root = tmp_path / "published"
    root.mkdir()
    old_appcast = b"<rss>old</rss>"
    old_manifest = b'{"version":"old"}\n'
    (root / "beta.xml").write_bytes(old_appcast)
    (root / "beta.json").write_bytes(old_manifest)
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"release")
    digest = sha256(b"release").hexdigest()
    appcast = _appcast(
        tmp_path / "appcast.xml",
        version="1.2.3",
        build=42,
        channel="beta",
        url=f"https://factor.example/assets/beta/{digest}.dmg",
    )

    publication = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
    )
    publication.rollback()

    assert (root / "beta.xml").read_bytes() == old_appcast
    assert (root / "beta.json").read_bytes() == old_manifest
    assert not (root / "assets/beta" / f"{digest}.dmg").exists()
    assert not (root / "appcasts/beta" / f"{digest}.xml").exists()


def test_beta_release_key_must_match_packaged_trust_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    trusted = tmp_path / "trusted.pem"
    trusted.write_text("trusted", encoding="utf-8")
    supplied = tmp_path / "supplied.pem"
    supplied.write_text("different", encoding="utf-8")
    monkeypatch.setattr(publish, "REPO", tmp_path)
    expected = tmp_path / "tools/cli/release/trusted-beta-release-public.pem"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(trusted.read_bytes())

    with pytest.raises(ValueError, match="does not match"):
        publish._validate_legacy_release_key("beta", supplied)


def test_release_rejects_mismatched_manifest_key_pair(tmp_path: Path) -> None:
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    other_private_key = tmp_path / "other-private.pem"
    subprocess.run(
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(private_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(other_private_key)],
        check=True,
        capture_output=True,
    )

    publish._validate_legacy_release_key_pair(private_key, public_key)
    with pytest.raises(ValueError, match="does not match"):
        publish._validate_legacy_release_key_pair(
            other_private_key,
            public_key,
        )


def test_release_rejects_drifted_apple_trust_root(tmp_path: Path) -> None:
    cli = tmp_path / "tools/cli/release"
    app = tmp_path / "apple/Resources/Shared"
    cli.mkdir(parents=True)
    app.mkdir(parents=True)
    for name in (
        "trusted-beta-release-public.pem",
        "trusted-release-public.pem",
    ):
        (cli / name).write_text("trusted", encoding="utf-8")
        (app / name).write_text("trusted", encoding="utf-8")
    (app / "trusted-beta-release-public.pem").write_text(
        "drifted",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="differs"):
        publish._validate_release_trust_root_copies(tmp_path)


def test_release_rejects_wrong_embedded_trust_root(tmp_path: Path) -> None:
    expected = tmp_path / "trusted.pem"
    expected.write_text("trusted", encoding="utf-8")
    embedded = (
        tmp_path
        / "FTClient.app/Contents/Resources/trusted-beta-release-public.pem"
    )
    embedded.parent.mkdir(parents=True)
    embedded.write_text("drifted", encoding="utf-8")

    with pytest.raises(ValueError, match="embeds a different"):
        publish._validate_embedded_release_trust_root(
            tmp_path / "FTClient.app",
            channel="beta",
            expected=expected,
        )


def test_delta_only_cleanup_removes_transient_full_archive(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "FactorTester-Client.dmg"
    archive.write_bytes(b"transient full archive")

    publish._remove_local_archive(archive)

    assert not archive.exists()


def test_delta_only_local_identity_is_restricted_to_loopback() -> None:
    assert publish._is_loopback_release_origin("http://127.0.0.1:8141")
    assert publish._is_loopback_release_origin("http://localhost:8141")
    assert not publish._is_loopback_release_origin("https://factor.example")
    with pytest.raises(ValueError, match="loopback Beta server"):
        publish.release_client(
            channel="beta",
            version="1.2.3",
            build=42,
            source_revision="a" * 40,
            output=Path("/tmp/unused-release-output"),
            signing_identity=publish.SHARED_SIGNING_IDENTITY,
            sparkle_public_key="public",
            sparkle_generate_appcast=Path("/tmp/generate_appcast"),
            legacy_private_key=Path("/tmp/private.pem"),
            legacy_public_key=Path("/tmp/public.pem"),
            server_origin="https://factor.example",
            release_root=Path("/tmp/release-root"),
            delta_only=True,
        )


def test_release_rejects_stale_client_packages_before_xcode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        publish, "_shared_signing_certificate",
        lambda: publish.SHARED_SIGNING_CERTIFICATE_SHA1,
    )
    monkeypatch.setattr(
        publish, "_validate_source_checkout",
        lambda _repo, _revision: None,
    )
    monkeypatch.setattr(
        publish, "_validate_legacy_release_key",
        lambda _channel, _key: None,
    )
    monkeypatch.setattr(
        publish, "_validate_legacy_release_key_pair",
        lambda _private, _public: None,
    )
    monkeypatch.setattr(
        publish, "_validate_release_trust_root_copies",
        lambda _repo: None,
    )

    def reject_layout(_repo: Path) -> None:
        raise ValueError("client package directories are missing")

    monkeypatch.setattr(
        publish, "validate_client_package_layout", reject_layout,
    )
    monkeypatch.setattr(
        publish, "xcodebuild_environment",
        lambda: pytest.fail("Xcode must not run after a package layout failure"),
    )

    with pytest.raises(ValueError, match="package directories are missing"):
        publish.release_client(
            channel="beta",
            version="1.2.3",
            build=42,
            source_revision="a" * 40,
            output=tmp_path / "release",
            signing_identity=publish.SHARED_SIGNING_IDENTITY,
            sparkle_public_key="public",
            sparkle_generate_appcast=tmp_path / "generate_appcast",
            legacy_private_key=tmp_path / "private.pem",
            legacy_public_key=tmp_path / "public.pem",
            server_origin="http://127.0.0.1:8141",
            release_root=tmp_path / "release-root",
        )

    assert not (tmp_path / "release").exists()


def test_failed_release_removes_its_output_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        publish, "_shared_signing_certificate",
        lambda: publish.SHARED_SIGNING_CERTIFICATE_SHA1,
    )
    monkeypatch.setattr(
        publish, "_validate_source_checkout",
        lambda _repo, _revision: None,
    )
    monkeypatch.setattr(
        publish, "_validate_legacy_release_key",
        lambda _channel, _key: None,
    )
    monkeypatch.setattr(
        publish, "_validate_legacy_release_key_pair",
        lambda _private, _public: None,
    )
    monkeypatch.setattr(
        publish, "_validate_release_trust_root_copies",
        lambda _repo: None,
    )
    monkeypatch.setattr(
        publish, "validate_client_package_layout", lambda _repo: None,
    )
    monkeypatch.setattr(publish, "xcodebuild_environment", lambda: {})
    monkeypatch.setattr(
        publish.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "xcodegen")
        ),
    )
    output = tmp_path / "release"

    with pytest.raises(subprocess.CalledProcessError):
        publish.release_client(
            channel="beta",
            version="1.2.3",
            build=42,
            source_revision="a" * 40,
            output=output,
            signing_identity=publish.SHARED_SIGNING_IDENTITY,
            sparkle_public_key="public",
            sparkle_generate_appcast=tmp_path / "generate_appcast",
            legacy_private_key=tmp_path / "private.pem",
            legacy_public_key=tmp_path / "public.pem",
            server_origin="http://127.0.0.1:8141",
            release_root=tmp_path / "release-root",
        )

    assert not output.exists()


def test_clean_commit_receipt_is_persisted_with_its_source_mode(
    tmp_path: Path,
) -> None:
    current = publish.PublishedRelease(
        channel="beta",
        version="1.2.3",
        build=42,
        source_revision="a" * 40,
        dmg_sha256="b" * 64,
        signing_certificate_sha1=publish.SHARED_SIGNING_CERTIFICATE_SHA1,
        asset_url="http://127.0.0.1:8141/dmg",
        appcast_url="http://127.0.0.1:8141/appcast",
        legacy_manifest_url="http://127.0.0.1:8141/manifest",
    )
    clean = publish._persist_clean_commit_receipt(tmp_path, current)

    assert clean.source_mode == "clean-commit"
    assert json.loads(
        (tmp_path / "release-receipt.json").read_text()
    )["source_mode"] == "clean-commit"


def test_main_is_uploaded_as_draft_before_becoming_latest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    files = []
    for name in ("FTClient.dmg", "appcast.xml", "stable.json"):
        path = tmp_path / name
        path.write_text(name)
        files.append(path)
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(publish.subprocess, "run", run)
    publish.publish_main_github(
        repository="owner/repo",
        tag="client-v1.2.3-b42",
        title="FTClient 1.2.3 (42)",
        dmg=files[0],
        appcast=files[1],
        legacy_manifest_path=files[2],
    )

    assert calls[0][:4] == ["gh", "release", "create", "client-v1.2.3-b42"]
    assert "--draft" in calls[0]
    assert calls[1][:4] == ["gh", "release", "edit", "client-v1.2.3-b42"]
    assert "--draft=false" in calls[1]
    assert "--latest" in calls[1]


def test_readback_requires_exact_published_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = tmp_path / "artifact"
    expected.write_bytes(b"expected")
    monkeypatch.setattr(
        publish.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=b"different"
        ),
    )
    with pytest.raises(ValueError, match="readback"):
        publish.verify_remote_bytes("https://example.test/artifact", expected)


def test_public_cli_exposes_one_main_beta_release_command() -> None:
    result = CliRunner().invoke(operator_client, ["release", "--help"])

    assert result.exit_code == 0
    assert "--channel [stable|beta]" in result.output
    assert "--sparkle-generate-appcast" in result.output
    assert "--server-ca-file" in result.output
    assert "--notary-profile" in result.output
    assert "--delta-only" in result.output
    assert "--from-clean-commit" in result.output


def test_direct_publisher_does_not_expose_server_restart_options() -> None:
    result = CliRunner().invoke(
        operator_client,
        ["release", "--help"],
    )

    assert result.exit_code == 0
    assert "--service-port" not in result.output
    assert "--manager-source-mode" not in result.output
    assert "--manager-stop-mode" not in result.output


def test_script_publisher_entrypoint_bootstraps_repository() -> None:
    source_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(source_root / "scripts/release/publish.py"),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--service-port" not in result.stdout


def test_module_publisher_does_not_restart_manager_before_build(
    monkeypatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(
        publish,
        "release_client",
        lambda **_options: sentinel,
    )
    monkeypatch.setattr(publish, "_validate_source_checkout", lambda *_args: None)
    result = publish.publish_release(
        channel="stable",
        version="1.2.3",
        build=42,
        source_revision="a" * 40,
    )

    assert result is sentinel


def test_public_cli_exposes_explicit_app_update_state_machine() -> None:
    runner = CliRunner()

    result = runner.invoke(client, ["app-update", "--help"])

    assert result.exit_code == 0
    for command in ("check", "download", "restart"):
        assert command in result.output


def test_cli_update_actions_only_dispatch_to_ftclient_sparkle(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(app_update_control, "installed_client_app", lambda: None)
    monkeypatch.setattr(
        app_update_control.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    result = app_update_control.dispatch_app_update("download")

    assert commands == [
        ["open", "factortester://app-update?action=download"]
    ]
    assert result["handler"] == "FTClient/Sparkle"


def test_cli_update_targets_the_current_installed_app(monkeypatch) -> None:
    monkeypatch.setattr(
        app_update_control,
        "installed_client_app",
        lambda: Path("/Applications/FTClient.app"),
    )
    assert app_update_control._update_open_command(
        "factortester://app-update?action=check"
    ) == [
        "open",
        "-a",
        "/Applications/FTClient.app",
        "factortester://app-update?action=check",
    ]


def test_cli_download_waits_for_a_real_download_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    status = tmp_path / "app-update-status.json"
    status.write_text(json.dumps({
        "state": "available",
        "installed_version": "0.1.0",
        "latest_version": "0.2.0",
        "updated_at": "before",
    }))
    monkeypatch.setattr(app_update_control, "status_path", lambda: status)
    monkeypatch.setattr(app_update_control, "installed_client_app", lambda: None)

    def open_update(command, **_kwargs):
        assert command == [
            "open", "factortester://app-update?action=download"
        ]
        status.write_text(json.dumps({
            "state": "ready",
            "installed_version": "0.1.0",
            "latest_version": "0.2.0",
            "updated_at": "after",
        }))

    monkeypatch.setattr(app_update_control.subprocess, "run", open_update)

    result = app_update_control.dispatch_app_update("download", wait=1)

    assert result["status"]["state"] == "ready"
    assert "timed_out" not in result


def test_all_channels_require_the_existing_shared_signing_identity(
    tmp_path: Path,
) -> None:
    common = {
        "channel": "beta",
        "version": "1.2.3",
        "build": 42,
        "source_revision": "a" * 40,
        "output": tmp_path / "output",
        "signing_identity": "Different Release Identity",
        "sparkle_public_key": "public",
        "sparkle_generate_appcast": tmp_path / "generate_appcast",
        "legacy_private_key": tmp_path / "private.pem",
        "legacy_public_key": tmp_path / "public.pem",
        "server_origin": "https://factor.example",
        "release_root": tmp_path / "published",
        "notary_profile": "factortester-notary",
    }
    with pytest.raises(ValueError, match="existing shared"):
        publish.release_client(**common)


def test_shared_signing_identity_is_pinned_by_certificate_fingerprint(
    monkeypatch,
) -> None:
    fingerprint = publish.SHARED_SIGNING_CERTIFICATE_SHA1
    monkeypatch.setattr(
        publish.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (
            f'  1) {fingerprint} "FTClient Beta Release"\n'
            "     1 valid identities found\n"
        ),
    )

    assert publish._shared_signing_certificate() == fingerprint
