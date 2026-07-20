from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_release as commands
from tools.cli.release.profile import load_release_inputs
from tests.release.test_release_manifest import signed_manifest


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
