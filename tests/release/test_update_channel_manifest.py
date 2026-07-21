from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import subprocess

import pytest

from script.release.update_manifest import (
    create_update_manifest,
    verify_installer,
    write_update_manifest,
)
from tools.cli.release.update_channel import (
    is_dmg_url,
    is_published_at,
    is_semantic_version,
    resolve_update_manifest,
    validate_update_manifest,
)


CONTRACT_VECTORS = (
    Path(__file__).parent / "fixtures/update_contract_vectors.json"
)


def _keys(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    private = root / "private.pem"
    public = root / "public.pem"
    subprocess.run(
        [
            "openssl", "genpkey", "-algorithm", "EC",
            "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(private),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl", "pkey", "-in", str(private), "-pubout",
            "-out", str(public),
        ],
        check=True,
        capture_output=True,
    )
    return private, public


def _manifest(
    root: Path,
    *,
    channel: str = "stable",
    dmg_url: str | None = None,
) -> tuple[dict, Path, Path]:
    private, public = _keys(root / "keys")
    dmg = root / "FactorTester-Client.dmg"
    dmg.write_bytes(b"signed installer")
    manifest = create_update_manifest(
        version="1.2.3" if channel == "stable" else "1.3.0-beta.1",
        build=42,
        channel=channel,
        dmg=dmg,
        dmg_url=dmg_url or (
            "https://github.com/maix00/FactorTester-Client/releases/"
            "download/v1.2.3/FactorTester-Client.dmg"
        ),
        minimum_client="1.0.0",
        mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    return manifest, public, dmg


def test_update_manifest_is_compact_signed_and_verifies_installer(
    tmp_path: Path,
) -> None:
    manifest, public, dmg = _manifest(tmp_path)
    validated = validate_update_manifest(
        manifest, public_key=public, expected_channel="stable"
    )
    assert validated.version == "1.2.3"
    assert validated.build == 42
    assert validated.dmg_sha256 == manifest["sha256"]
    assert len(json.dumps(manifest)) < 4_000
    verify_installer(
        dmg, manifest, public_key=public, channel="stable"
    )
    path = write_update_manifest(tmp_path / "stable.json", manifest)
    assert path.read_text().endswith("\n")

    dmg.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        verify_installer(
            dmg, manifest, public_key=public, channel="stable"
        )


def test_main_uses_only_signed_github_and_beta_uses_only_server(
    tmp_path: Path,
) -> None:
    manifest, public, _ = _manifest(tmp_path)
    trusted = json.dumps(manifest).encode()
    tampered = json.loads(trusted)
    tampered["build"] = 43
    responses = {
        "https://factor.example/api/client/releases/stable.json": (
            json.dumps(tampered).encode()
        ),
        "https://github.example/stable.json": trusted,
    }

    requested: list[str] = []

    def opener(request, timeout):
        assert timeout == 15
        requested.append(request.full_url)
        return BytesIO(responses[request.full_url])

    _, validated, source = resolve_update_manifest(
        server_manifest_url=(
            "https://factor.example/api/client/releases/stable.json"
        ),
        github_manifest_url="https://github.example/stable.json",
        channel="stable",
        public_key=public,
        opener=opener,
    )
    assert source == "github"
    assert validated.build == 42
    assert requested == ["https://github.example/stable.json"]

    responses["https://github.example/stable.json"] = json.dumps(
        tampered
    ).encode()
    with pytest.raises(ValueError, match="no trusted"):
        resolve_update_manifest(
            server_manifest_url=(
                "https://factor.example/api/client/releases/stable.json"
            ),
            github_manifest_url="https://github.example/stable.json",
            channel="stable",
            public_key=public,
            opener=opener,
        )

    beta, beta_public, _ = _manifest(
        tmp_path / "beta",
        channel="beta",
        dmg_url="https://factor.example/releases/FTClient-beta.dmg",
    )
    responses["https://factor.example/api/client/releases/beta.json"] = (
        json.dumps(beta).encode()
    )
    responses["https://github.example/beta.json"] = b"not trusted"
    requested.clear()
    _, validated, source = resolve_update_manifest(
        server_manifest_url=(
            "https://factor.example/api/client/releases/beta.json"
        ),
        github_manifest_url="https://github.example/beta.json",
        channel="beta",
        public_key=beta_public,
        opener=opener,
    )
    assert source == "server"
    assert validated.version == "1.3.0-beta.1"
    assert requested == [
        "https://factor.example/api/client/releases/beta.json"
    ]


def test_beta_accepts_loopback_http_but_rejects_remote_http_and_cross_origin(
    tmp_path: Path,
) -> None:
    beta, public, _ = _manifest(
        tmp_path / "loopback",
        channel="beta",
        dmg_url=(
            "http://127.0.0.1:8141/api/client/releases/assets/beta/"
            "FTClient-1.3.0-beta.1.dmg"
        ),
    )

    def opener(request, timeout):
        assert request.full_url == (
            "http://127.0.0.1:8141/api/client/releases/beta.json"
        )
        return BytesIO(json.dumps(beta).encode())

    _, validated, source = resolve_update_manifest(
        server_manifest_url=(
            "http://127.0.0.1:8141/api/client/releases/beta.json"
        ),
        github_manifest_url="",
        channel="beta",
        public_key=public,
        opener=opener,
    )
    assert source == "server"
    assert validated.dmg_url.startswith("http://127.0.0.1:8141/")

    remote_private, remote_public = _keys(tmp_path / "remote-http" / "keys")
    remote_dmg = tmp_path / "remote-http" / "FTClient-beta.dmg"
    remote_dmg.write_bytes(b"remote beta")
    with pytest.raises(ValueError, match="HTTPS or loopback"):
        create_update_manifest(
            version="1.3.0-beta.1",
            build=42,
            channel="beta",
            dmg=remote_dmg,
            dmg_url="http://factor.example/FTClient-beta.dmg",
            minimum_client="1.0.0",
            mandatory=False,
            published_at="2026-07-20T12:00:00Z",
            private_key=remote_private,
            public_key=remote_public,
        )

    cross, cross_public, _ = _manifest(
        tmp_path / "cross-origin",
        channel="beta",
        dmg_url="https://cdn.example/FTClient-beta.dmg",
    )
    with pytest.raises(ValueError, match="manifest origin"):
        resolve_update_manifest(
            server_manifest_url="https://factor.example/beta.json",
            github_manifest_url="",
            channel="beta",
            public_key=cross_public,
            opener=lambda *_args, **_kwargs: BytesIO(
                json.dumps(cross).encode()
            ),
        )

    class RedirectedResponse(BytesIO):
        def geturl(self) -> str:
            return "http://factor.example/beta.json"

    with pytest.raises(ValueError, match="redirected to an untrusted URL"):
        resolve_update_manifest(
            server_manifest_url=(
                "http://127.0.0.1:8141/api/client/releases/beta.json"
            ),
            github_manifest_url="",
            channel="beta",
            public_key=public,
            opener=lambda *_args, **_kwargs: RedirectedResponse(
                json.dumps(beta).encode()
            ),
        )


@pytest.mark.parametrize(
    ("channel", "server_url", "github_url"),
    [
        ("stable", "https://ignored.example/stable.json", ""),
        ("beta", None, "https://ignored.example/beta.json"),
    ],
)
def test_channel_never_falls_back_to_the_other_source(
    tmp_path: Path,
    channel: str,
    server_url: str | None,
    github_url: str,
) -> None:
    _, public, _ = _manifest(tmp_path, channel=channel)

    with pytest.raises(ValueError, match=f"trusted {channel}"):
        resolve_update_manifest(
            server_manifest_url=server_url,
            github_manifest_url=github_url,
            channel=channel,
            public_key=public,
            opener=lambda *_args, **_kwargs: pytest.fail(
                "non-authoritative source must not be requested"
            ),
        )


def test_channel_and_minimum_client_are_signed_fields(tmp_path: Path) -> None:
    manifest, public, _ = _manifest(tmp_path)
    manifest["minimum_client"] = "9.0.0"
    with pytest.raises(ValueError, match="signature"):
        validate_update_manifest(manifest, public_key=public)


def test_main_and_beta_signing_roots_cannot_validate_each_other(
    tmp_path: Path,
) -> None:
    main, main_public, _ = _manifest(tmp_path / "main")
    beta, beta_public, _ = _manifest(
        tmp_path / "beta-cross-key",
        channel="beta",
        dmg_url="https://factor.example/FTClient-beta.dmg",
    )

    with pytest.raises(ValueError, match="key ID"):
        validate_update_manifest(
            main, public_key=beta_public, expected_channel="stable"
        )
    with pytest.raises(ValueError, match="key ID"):
        validate_update_manifest(
            beta, public_key=main_public, expected_channel="beta"
        )


def test_python_update_contract_matches_shared_vectors() -> None:
    vectors = json.loads(CONTRACT_VECTORS.read_text(encoding="utf-8"))
    for value in vectors["valid_versions"]:
        assert is_semantic_version(value), value
    for value in vectors["invalid_versions"]:
        assert not is_semantic_version(value), value
    for value in vectors["valid_published_at"]:
        assert is_published_at(value), value
    for value in vectors["invalid_published_at"]:
        assert not is_published_at(value), value
    for value in vectors["valid_dmg_urls"]:
        assert is_dmg_url(value), value
    for value in vectors["invalid_dmg_urls"]:
        assert not is_dmg_url(value), value
