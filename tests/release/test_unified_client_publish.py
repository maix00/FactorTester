from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

from click.testing import CliRunner
import pytest

from script.release import publish
from tools.cli.commands.client_release import client_release
from tools.cli.release import app_update_control


def test_release_rejects_a_drifted_cli_anything_skill_copy(
    tmp_path: Path,
) -> None:
    source_root = Path(__file__).resolve().parents[2]
    script = (
        source_root / "tools/cli/agent-harness/scripts/sync_skill.py"
    )
    canonical = (
        tmp_path / "skills/cli-anything-factortester-research/SKILL.md"
    )
    packaged = (
        tmp_path
        / "tools/cli/agent-harness/cli_anything/factortester_research/skills/SKILL.md"
    )
    target_script = tmp_path / "tools/cli/agent-harness/scripts/sync_skill.py"
    resources = tmp_path / "tools/cli/agent-harness/cli_anything/factortester_research/resources"
    canonical.parent.mkdir(parents=True)
    packaged.parent.mkdir(parents=True)
    target_script.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    canonical.write_text("canonical", encoding="utf-8")
    packaged.write_text("stale", encoding="utf-8")
    (resources / "capabilities.v1.json").write_text(
        '{"capabilities": []}', encoding="utf-8",
    )
    (resources / "provider-locks.v1.json").write_text(
        '{"implementations": {}}', encoding="utf-8",
    )
    shutil.copy2(script, target_script)

    with pytest.raises(ValueError, match="Skill copies are out of sync"):
        publish._validate_cli_anything_skill_copy(tmp_path)

    subprocess.run(
        [
            sys.executable, str(target_script), "--repo", str(tmp_path), "--write",
        ],
        check=True,
    )
    publish._validate_cli_anything_skill_copy(tmp_path)


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

    asset, xml_pointer, json_pointer = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
        deltas=(delta,),
    )

    assert asset == root / "assets/beta" / f"{digest}.dmg"
    assert xml_pointer.read_bytes() == appcast.read_bytes()
    assert json.loads(json_pointer.read_text())["sha256"] == digest
    assert (root / "assets/beta/delta.sha256.delta").read_bytes() == b"delta"


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

    publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
        publish_full=True,
    )

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

    asset, _, _ = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": "a" * 64},
        release_root=root,
        deltas=(delta,),
        publish_full=False,
        retain_base=True,
    )

    assert asset == root / "assets/beta" / f"{sha256(b'release').hexdigest()}.dmg"
    assert not asset.exists()
    assert (
        root / "bases/beta" / f"{sha256(b'release').hexdigest()}.dmg"
    ).read_bytes() == b"release"
    assert (root / "assets/beta" / delta.name).read_bytes() == b"delta"
    assert not old_asset.exists()
    assert not old_delta.exists()
    assert not old_appcast.exists()
    assert not list(root.rglob("*.staging-*"))


def test_delta_only_cleanup_removes_transient_full_archive(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "FactorTester-Client.dmg"
    archive.write_bytes(b"transient full archive")

    publish._remove_local_archive(archive)

    assert not archive.exists()


def test_delta_only_requires_trusted_signing_identity() -> None:
    with pytest.raises(ValueError, match="trusted Developer ID"):
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
            server_origin="http://127.0.0.1:8141",
            release_root=Path("/tmp/release-root"),
            delta_only=True,
        )


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
    result = CliRunner().invoke(client_release, ["release", "--help"])

    assert result.exit_code == 0
    assert "--channel [stable|beta]" in result.output
    assert "--sparkle-generate-appcast" in result.output
    assert "--notary-profile" in result.output
    assert "--delta-only" in result.output
    assert "--from-clean-commit" in result.output


def test_public_cli_exposes_explicit_app_update_state_machine() -> None:
    runner = CliRunner()

    result = runner.invoke(client_release, ["app-update", "--help"])

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
