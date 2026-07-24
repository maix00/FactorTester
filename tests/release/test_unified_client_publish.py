from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

from click.testing import CliRunner
import pytest

from script.release import publish
from tools.cli.commands.client_release import client_release


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

    asset, xml_pointer, json_pointer = publish.publish_beta_directory(
        dmg=dmg,
        appcast=appcast,
        legacy_manifest={"schema_version": 1, "sha256": digest},
        release_root=root,
    )

    assert asset == root / "assets/beta" / f"{digest}.dmg"
    assert xml_pointer.read_bytes() == appcast.read_bytes()
    assert json.loads(json_pointer.read_text())["sha256"] == digest
    assert not list(root.rglob("*.staging-*"))


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
