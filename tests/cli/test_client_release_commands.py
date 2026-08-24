from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.release.test_release_manifest import signed_manifest
from tools.cli.app import cli
from tools.cli.commands import client_release as commands
from tools.cli.manager_app import manager_cli
from tools.cli.release import profile as release_profile
from tools.cli.release.profile import (
    MAIN_GITHUB_MANIFEST_URL,
    load_release_inputs,
    load_update_inputs,
)
from tools.cli.release.update_channel import ValidatedUpdateManifest


def test_beta_release_upload_only_skips_network_failures() -> None:
    assert commands._release_target_offline(ConnectionError("refused"))
    assert commands._release_target_offline(TimeoutError("timed out"))
    assert not commands._release_target_offline(FileNotFoundError("local package"))
    assert not commands._release_target_offline(ValueError("bad manifest"))


def test_client_bootstrap_dry_run_is_machine_readable_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest, public_key = signed_manifest(tmp_path / "signed")
    install_root = tmp_path / "support"
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        commands,
        "load_release_inputs",
        lambda _profile: (manifest, public_key, install_root),
    )

    result = CliRunner().invoke(
        cli,
        [
            "client",
            "bootstrap",
            "--profile",
            str(profile),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target_version"] == "1.2.3"
    assert payload["mutations"]
    assert not install_root.exists()


def test_client_release_help_exposes_no_secret_arguments() -> None:
    result = CliRunner().invoke(cli, ["client", "bootstrap", "--help"])

    assert result.exit_code == 0
    assert "--profile" in result.output
    assert "--dry-run" in result.output
    assert "password" not in result.output.lower()
    assert "token" not in result.output.lower()


def test_publish_release_does_not_require_a_manager_service_port() -> None:
    result = CliRunner().invoke(
        manager_cli, ["client", "release", "--help"],
    )

    assert result.exit_code == 0
    assert "--service-port" not in result.output


def test_bundled_publisher_uses_current_source_checkout(
    tmp_path: Path, monkeypatch,
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "scripts" / "release").mkdir(parents=True)
    (checkout / "scripts" / "release" / "publish.py").write_text(
        "# release entrypoint\n", encoding="utf-8",
    )
    monkeypatch.chdir(checkout)

    assert commands._release_source_root() == checkout


def test_frozen_publisher_delegates_complete_release_to_host_python(
    tmp_path: Path, monkeypatch,
) -> None:
    source_root = tmp_path / "checkout"
    entrypoint = source_root / "scripts/release/publish.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("# release entrypoint\n", encoding="utf-8")
    calls = []
    monkeypatch.setenv("FTCLIENT_RELEASE_PYTHON", "/host/python3")
    monkeypatch.setattr(
        commands.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    commands._run_release_with_host_python(source_root, {
        "channel": "beta",
        "source_revision": "a" * 40,
        "output": tmp_path / "output",
        "mandatory": True,
        "notary_profile": None,
        "delta_only": False,
    })

    command, kwargs = calls[0]
    assert command[:2] == ["/host/python3", str(entrypoint)]
    assert command[2:] == [
        "--channel", "beta",
        "--source-revision", "a" * 40,
        "--output", str(tmp_path / "output"),
        "--mandatory",
    ]
    assert kwargs == {"cwd": source_root, "check": True}


def test_profile_cannot_replace_packaged_release_trust_anchor(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": 1,
        "release": {
            "manifest_url": "https://example.invalid/manifest.json",
            "public_key": "/tmp/attacker.pem",
        },
    }), encoding="utf-8")

    try:
        load_release_inputs(profile)
    except ValueError as exc:
        assert "fixed by the client package" in str(exc)
    else:
        raise AssertionError("profile replaced packaged trust anchor")


def test_check_update_reports_only_verified_server_first_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    update = ValidatedUpdateManifest(
        version="2.0.0",
        build=9,
        channel="beta",
        dmg_url="https://github.example/FactorTester-Client.dmg",
        dmg_sha256="a" * 64,
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        manifest_hash="b" * 64,
    )
    monkeypatch.setattr(
        commands,
        "load_update_inputs",
        lambda _: ({}, update, "server"),
    )
    result = CliRunner().invoke(cli, [
        "client", "check-update", "--profile", str(profile), "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "schema_version": 1,
        "source": "server",
        "version": "2.0.0",
        "build": 9,
        "channel": "beta",
        "dmg_url": "https://github.example/FactorTester-Client.dmg",
        "sha256": "a" * 64,
        "minimum_client": "1.2.0",
        "mandatory": False,
        "published_at": "2026-07-20T12:00:00Z",
        "manifest_hash": "b" * 64,
        "signature_verified": True,
    }


def test_main_update_source_is_fixed_before_network_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": 1,
        "release": {
            "channel": "stable",
            "github_manifest_url": "https://example.test/stable.json",
        },
    }))
    monkeypatch.setattr(
        release_profile,
        "resolve_update_manifest",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("network resolver must not be called")
        ),
    )

    try:
        load_update_inputs(profile)
    except ValueError as exc:
        assert "fixed to the public GitHub release" in str(exc)
    else:
        raise AssertionError("non-GitHub Main source was accepted")


def test_main_update_source_defaults_to_public_github(
    tmp_path: Path,
    monkeypatch,
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "schema_version": 1,
        "release": {"channel": "stable"},
    }))
    captured = {}
    expected = ({}, object(), "github")

    def resolve(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(release_profile, "resolve_update_manifest", resolve)

    assert load_update_inputs(profile) == expected
    assert captured["github_manifest_url"] == MAIN_GITHUB_MANIFEST_URL
