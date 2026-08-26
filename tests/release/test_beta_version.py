from __future__ import annotations

import json
import ssl
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts.release import publish
from tools.cli.release import beta_version
from tools.cli.release.beta_version import (
    BetaSourceTrustError,
    ExistingBetaRelease,
    next_beta_version,
    parse_beta_version,
    read_installed_beta_release,
    resolve_beta_identity,
)


def _project(path: Path, *, version: str = "0.1.3-dev", build: int = 35) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "settings:\n"
        f'  MARKETING_VERSION: "{version}"\n'
        f'  CURRENT_PROJECT_VERSION: "{build}"\n',
        encoding="utf-8",
    )
    return path


def _manifest(root: Path, *, version: str, build: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "beta.json").write_text(
        json.dumps({"version": version, "build": build}),
        encoding="utf-8",
    )
    return root


def test_next_beta_version_uses_the_highest_published_ordinal() -> None:
    releases = [
        ExistingBetaRelease("0.1.3-beta.2", 10, "a"),
        ExistingBetaRelease("0.1.3-beta.32", 35, "b"),
    ]

    assert next_beta_version(
        releases,
        project_base_version="0.1.3",
    ) == "0.1.3-beta.33"


def test_resolve_beta_identity_reads_all_available_roots(tmp_path: Path) -> None:
    project = _project(tmp_path / "project.yml")
    first = _manifest(
        tmp_path / "first",
        version="0.1.3-beta.32",
        build=35,
    )
    second = _manifest(
        tmp_path / "second",
        version="0.1.3-beta.34",
        build=40,
    )

    version, build, discovered = resolve_beta_identity(
        version="auto",
        build="auto",
        sources=(first, second),
        project_file=project,
    )

    assert version == "0.1.3-beta.35"
    assert build == 41
    assert {item.source for item in discovered} == {
        str(first / "beta.json"),
        str(second / "beta.json"),
    }


def test_resolve_beta_identity_skips_an_offline_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path / "project.yml")
    online = _manifest(
        tmp_path / "online",
        version="0.1.3-beta.32",
        build=35,
    )

    def offline(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(beta_version, "urlopen", offline)
    version, build, discovered = resolve_beta_identity(
        version=None,
        build=None,
        sources=(online, "https://offline.example"),
        project_file=project,
    )

    assert version == "0.1.3-beta.33"
    assert build == 36
    assert len(discovered) == 1


def test_resolve_beta_identity_fails_closed_on_tls_trust_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path / "project.yml")

    def untrusted(*_args, **_kwargs):
        raise URLError(ssl.SSLCertVerificationError("self-signed certificate"))

    monkeypatch.setattr(beta_version, "urlopen", untrusted)
    with pytest.raises(BetaSourceTrustError, match="TLS identity"):
        resolve_beta_identity(
            version="auto",
            build="auto",
            sources=("https://reachable.example",),
            project_file=project,
        )


def test_beta_manifest_uses_the_explicit_ca_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ca_file = tmp_path / "manager-ca.pem"
    ca_file.write_text("test certificate", encoding="utf-8")
    context = object()
    observed: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            return b'{"version":"0.1.3-beta.36","build":43}'

    def create_context(*, cafile: str):
        observed["cafile"] = cafile
        return context

    def open_manifest(_request, *, timeout: int, context: object):
        observed["timeout"] = timeout
        observed["context"] = context
        return Response()

    monkeypatch.setattr(beta_version.ssl, "create_default_context", create_context)
    monkeypatch.setattr(beta_version, "urlopen", open_manifest)

    release = beta_version.read_beta_release(
        "https://manager.example",
        ca_file=ca_file,
    )

    assert release == ExistingBetaRelease(
        "0.1.3-beta.36",
        43,
        "https://manager.example/api/client/releases/beta.json",
    )
    assert observed == {
        "cafile": str(ca_file),
        "timeout": 15,
        "context": context,
    }


def test_explicit_beta_version_must_be_newer_than_discovered_release(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path / "project.yml")
    root = _manifest(
        tmp_path / "published",
        version="0.1.3-beta.32",
        build=35,
    )

    with pytest.raises(ValueError, match="not newer"):
        resolve_beta_identity(
            version="0.1.3-beta.32",
            build="auto",
            sources=(root,),
            project_file=project,
        )


def test_parse_beta_version_rejects_non_beta_versions() -> None:
    assert parse_beta_version("1.2.3-beta.7") == (1, 2, 3, 7)
    with pytest.raises(ValueError, match="X.Y.Z-beta.N"):
        parse_beta_version("1.2.3")


def test_installed_beta_app_is_a_local_version_floor(tmp_path: Path) -> None:
    info = tmp_path / "Info.plist"
    info.write_bytes(plist_bytes(
        "0.1.3-beta.32",
        "35",
    ))

    release = read_installed_beta_release(info)

    assert release is not None
    assert release.version == "0.1.3-beta.32"
    assert release.build == 35


def plist_bytes(version: str, build: str) -> bytes:
    import plistlib

    return plistlib.dumps({
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
    })


def test_publish_transaction_resolves_auto_identity_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    project = _project(repo / "apple/project.yml")
    release_root = _manifest(
        tmp_path / "published",
        version="0.1.3-beta.32",
        build=35,
    )
    monkeypatch.setattr(publish, "REPO", repo)
    monkeypatch.setattr(publish, "_validate_source_checkout", lambda *_args: None)
    # The test's temporary release root is the complete discovery scope;
    # ignore any locally installed FTClient.app on the developer machine.
    monkeypatch.setattr(publish, "read_installed_beta_release", lambda *_args: None)
    captured: dict[str, object] = {}

    def fake_release_client(**options):
        captured.update(options)
        return options

    monkeypatch.setattr(publish, "release_client", fake_release_client)
    result = publish.publish_release(
        channel="beta",
        version="auto",
        build="auto",
        source_revision="a" * 40,
        release_root=release_root,
        server_origin=None,
    )

    assert result["version"] == "0.1.3-beta.33"
    assert result["build"] == 36
    assert captured["version"] == "0.1.3-beta.33"
    assert captured["build"] == 36
    assert project.is_file()


def test_publish_transaction_stops_before_build_on_tls_trust_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _project(repo / "apple/project.yml")
    monkeypatch.setattr(publish, "REPO", repo)
    monkeypatch.setattr(publish, "_validate_source_checkout", lambda *_args: None)
    monkeypatch.setattr(publish, "read_installed_beta_release", lambda *_args: None)
    built = False

    def untrusted(*_args, **_kwargs):
        raise URLError(ssl.SSLCertVerificationError("untrusted"))

    def release_client(**_options):
        nonlocal built
        built = True

    monkeypatch.setattr(beta_version, "urlopen", untrusted)
    monkeypatch.setattr(publish, "release_client", release_client)

    with pytest.raises(BetaSourceTrustError):
        publish.publish_release(
            channel="beta",
            version="auto",
            build="auto",
            source_revision="a" * 40,
            server_origin="https://manager.example",
        )

    assert built is False
