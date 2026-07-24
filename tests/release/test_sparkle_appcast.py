from __future__ import annotations

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
        generated = Path(command[-1]) / "appcast.xml"
        generated.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"
 version="2.0"><channel><item><title>0.2.0</title>
<sparkle:version>4</sparkle:version>
<sparkle:shortVersionString>0.2.0</sparkle:shortVersionString>
<enclosure url="https://example.test/FactorTester-Client.dmg"
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
        download_url="https://example.test/FactorTester-Client.dmg",
        version="0.2.0",
        build=4,
        channel="stable",
    )

    assert appcast == SparkleAppcast(
        path=output,
        version="0.2.0",
        build=4,
        channel="stable",
        download_url="https://example.test/FactorTester-Client.dmg",
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
