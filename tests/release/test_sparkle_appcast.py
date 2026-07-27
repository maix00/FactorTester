from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

import pytest

from script.release.sparkle import (
    SparkleAppcast,
    generate_sparkle_appcast,
    is_secure_release_url,
    validate_sparkle_appcast,
)


def _tool(root: Path, name: str) -> Path:
    path = root / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_generate_appcast_uses_keychain_tool_without_plaintext_key(
    tmp_path: Path, monkeypatch,
) -> None:
    archive = tmp_path / "FactorTester-Client.dmg"
    archive.write_bytes(b"dmg")
    output = tmp_path / "appcast.xml"
    tool = _tool(tmp_path, "generate_appcast")
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        root = Path(command[-1])
        assert (root / "release-sha.dmg").read_bytes() == b"dmg"
        generated = root / "appcast.xml"
        generated.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item><title>0.2.0</title>
<sparkle:version>4</sparkle:version>
<sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
<enclosure url="https://example.test/release-sha.dmg"
 sparkle:edSignature="signed" length="3"
 type="application/octet-stream"/></item></channel></rss>
""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    appcast = generate_sparkle_appcast(
        archive=archive,
        output=output,
        tool=tool,
        download_url="https://example.test/release-sha.dmg",
        version="0.2.0",
        build=4,
        channel="stable",
    )

    assert appcast == SparkleAppcast(
        path=output,
        version="0.2.0",
        build=4,
        channel="stable",
        download_url="https://example.test/release-sha.dmg",
    )
    flattened = " ".join(calls[0])
    assert "--ed-key-file" not in flattened
    assert "-s " not in f"{flattened} "


def test_appcast_rejects_wrong_release_identity(tmp_path: Path) -> None:
    path = tmp_path / "appcast.xml"
    path.write_text(
        """<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item>
<sparkle:version>5</sparkle:version>
<sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
<enclosure url="https://example.test/FactorTester-Client.dmg"
 sparkle:edSignature="signed" length="3"/>
</item></channel></rss>""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="build"):
        validate_sparkle_appcast(
            path,
            version="0.2.0",
            build=4,
            channel="stable",
            download_url="https://example.test/FactorTester-Client.dmg",
        )


def test_generate_appcast_stages_previous_archive_and_publishes_content_addressed_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "current.dmg"
    archive.write_bytes(b"current")
    previous = tmp_path / "previous.dmg"
    previous.write_bytes(b"previous")
    previous_appcast = tmp_path / "previous-appcast.xml"
    previous_appcast.write_text(
        """<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item><sparkle:version>4</sparkle:version>
<sparkle:shortVersionString>0.1.0</sparkle:shortVersionString>
<enclosure url="https://example.test/previous.dmg" sparkle:edSignature="signed" />
</item></channel></rss>""",
        encoding="utf-8",
    )
    output = tmp_path / "appcast.xml"
    delta_output = tmp_path / "deltas"
    tool = _tool(tmp_path, "generate_appcast")
    delta_payload = b"delta-payload"

    def run(command, **kwargs):
        root = Path(command[-1])
        assert (root / "previous.dmg").read_bytes() == b"previous"
        assert (root / "previous.dmg").is_file()
        (root / "FTClient5-4.delta").write_bytes(delta_payload)
        (root / "appcast.xml").write_text(
            """<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item>
<sparkle:version>5</sparkle:version>
<sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
<enclosure url="https://example.test/current.dmg" sparkle:edSignature="signed" />
<sparkle:deltas><enclosure url="https://example.test/FTClient5-4.delta"
 sparkle:deltaFrom="4" sparkle:edSignature="signed" /></sparkle:deltas>
</item></channel></rss>""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    generated = generate_sparkle_appcast(
        archive=archive,
        output=output,
        tool=tool,
        download_url="https://example.test/current.dmg",
        version="0.2.0",
        build=5,
        channel="stable",
        previous_archive=previous,
        previous_archive_url="https://example.test/previous.dmg",
        previous_appcast=previous_appcast,
        delta_output=delta_output,
    )

    digest = sha256(delta_payload).hexdigest()
    assert generated.delta_paths == (delta_output / f"{digest}.delta",)
    text = output.read_text(encoding="utf-8")
    assert f"https://example.test/{digest}.delta" in text
    assert "FTClient5-4.delta" not in text


def test_delta_only_appcast_keeps_only_the_matching_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = tmp_path / "current.dmg"
    archive.write_bytes(b"current")
    previous = tmp_path / "previous.dmg"
    previous.write_bytes(b"previous")
    output = tmp_path / "appcast.xml"
    delta_output = tmp_path / "deltas"
    previous_appcast = tmp_path / "previous-appcast.xml"
    previous_appcast.write_text(
        """<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item><sparkle:version>4</sparkle:version>
<sparkle:shortVersionString>0.1.0</sparkle:shortVersionString>
<enclosure url="https://example.test/previous.dmg" sparkle:edSignature="signed" />
</item></channel></rss>""",
        encoding="utf-8",
    )
    tool = _tool(tmp_path, "generate_appcast")

    def run(command, **kwargs):
        root = Path(command[-1])
        (root / "FTClient5-4.delta").write_bytes(b"delta")
        (root / "appcast.xml").write_text(
            """<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel>
<item><sparkle:version>5</sparkle:version>
<sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
<sparkle:channel>beta</sparkle:channel>
<enclosure url="https://example.test/current.dmg" sparkle:edSignature="signed" />
<sparkle:deltas><enclosure url="https://example.test/FTClient5-4.delta"
 sparkle:deltaFrom="4" sparkle:edSignature="signed" /></sparkle:deltas></item>
<item><sparkle:version>4</sparkle:version>
<sparkle:shortVersionString>0.1.0</sparkle:shortVersionString>
<sparkle:channel>beta</sparkle:channel>
<enclosure url="https://example.test/previous.dmg" sparkle:edSignature="signed" />
</item></channel></rss>""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    generate_sparkle_appcast(
        archive=archive,
        output=output,
        tool=tool,
        download_url="https://example.test/current.dmg",
        version="0.2.0",
        build=5,
        channel="beta",
        previous_archive=previous,
        previous_appcast=previous_appcast,
        delta_output=delta_output,
        delta_only=True,
    )

    assert output.read_text(encoding="utf-8").count("<item>") == 1


def test_release_url_allows_loopback_http_but_not_public_http() -> None:
    assert is_secure_release_url(
        "http://127.0.0.1:8141/api/client/releases/beta.xml"
    )
    assert is_secure_release_url(
        "http://localhost:8141/api/client/releases/beta.xml"
    )
    assert is_secure_release_url(
        "http://[::1]:8141/api/client/releases/beta.xml"
    )
    assert is_secure_release_url(
        "https://factor.example/api/client/releases/beta.xml"
    )
    assert not is_secure_release_url(
        "http://factor.example/api/client/releases/beta.xml"
    )
