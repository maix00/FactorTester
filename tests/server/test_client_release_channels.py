from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

from flask import Flask
from werkzeug.serving import make_server

from script.release.update_manifest import (
    create_update_manifest,
    write_update_manifest,
)
from server.auth import auth_bp
from server.modules.shared import shared_bp
from server.modules.shared import client_releases as routes
from tests.release.test_update_channel_manifest import _keys
from tools.cli.release.update_channel import resolve_update_manifest


def _write_beta_appcast(
    path: Path,
    *,
    dmg_url: str,
    channel: str = "beta",
    signature: str = "sparkle-signature",
) -> bytes:
    raw = f"""<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <item>
      <sparkle:version>7</sparkle:version>
      <sparkle:shortVersionString>2.0.0</sparkle:shortVersionString>
      <sparkle:channel>{channel}</sparkle:channel>
      <enclosure url="{dmg_url}" sparkle:edSignature="{signature}" />
    </item>
  </channel>
</rss>
""".encode()
    path.write_bytes(raw)
    return raw


def test_beta_sparkle_appcast_is_verified_cacheable_and_conditional(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    dmg = root / "assets/beta" / ("a" * 64 + ".dmg")
    dmg.parent.mkdir(parents=True)
    dmg.write_bytes(b"installer")
    actual_digest = sha256(dmg.read_bytes()).hexdigest()
    actual = dmg.with_name(f"{actual_digest}.dmg")
    dmg.rename(actual)
    dmg_url = (
        "http://127.0.0.1:8141/api/client/releases/assets/beta/"
        f"{actual.name}"
    )
    manifest = create_update_manifest(
        version="2.0.0",
        build=7,
        channel="beta",
        dmg=actual,
        dmg_url=dmg_url,
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", manifest)
    raw = _write_beta_appcast(root / "beta.xml", dmg_url=dmg_url)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    response = client.get("/api/client/releases/beta.xml")
    assert response.status_code == 200
    assert response.data == raw
    assert response.mimetype == "application/rss+xml"
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    cached = client.get(
        "/api/client/releases/beta.xml",
        headers={"If-None-Match": response.headers["ETag"]},
    )
    assert cached.status_code == 304
    assert cached.data == b""


def test_beta_sparkle_appcast_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    root.mkdir()
    dmg = tmp_path / "installer.dmg"
    dmg.write_bytes(b"installer")
    digest = sha256(dmg.read_bytes()).hexdigest()
    dmg_url = (
        "https://factor.example/api/client/releases/assets/beta/"
        f"{digest}.dmg"
    )
    manifest = create_update_manifest(
        version="2.0.0",
        build=7,
        channel="beta",
        dmg=dmg,
        dmg_url=dmg_url,
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", manifest)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()
    appcast = root / "beta.xml"

    assert client.get("/api/client/releases/beta.xml").status_code == 404
    assert client.get("/api/client/releases/stable.xml").status_code == 404
    appcast.write_text("<not-xml")
    assert client.get("/api/client/releases/beta.xml").status_code == 503
    appcast.write_bytes(b"x" * (1024 * 1024 + 1))
    assert client.get("/api/client/releases/beta.xml").status_code == 503
    _write_beta_appcast(
        appcast,
        dmg_url=dmg_url,
        channel="stable",
    )
    assert client.get("/api/client/releases/beta.xml").status_code == 503
    _write_beta_appcast(appcast, dmg_url=dmg_url, signature="")
    assert client.get("/api/client/releases/beta.xml").status_code == 503
    _write_beta_appcast(
        appcast,
        dmg_url="https://factor.example/wrong.dmg",
    )
    assert client.get("/api/client/releases/beta.xml").status_code == 503
    target = root / "real-beta.xml"
    _write_beta_appcast(target, dmg_url=dmg_url)
    appcast.unlink()
    appcast.symlink_to(target)
    assert client.get("/api/client/releases/beta.xml").status_code == 503


def test_beta_release_channel_is_static_cacheable_and_conditional(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    dmg = tmp_path / "FactorTester-Client.dmg"
    dmg.write_bytes(b"installer")
    digest_name = f"{sha256(dmg.read_bytes()).hexdigest()}.dmg"
    manifest = create_update_manifest(
        version="2.0.0",
        build=7,
        channel="beta",
        dmg=dmg,
        dmg_url=(
            "https://factor.example/api/client/releases/assets/beta/"
            f"{digest_name}"
        ),
        minimum_client="1.2.0",
        mandatory=True,
        published_at="2026-07-20T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    root = tmp_path / "channels"
    write_update_manifest(root / "beta.json", manifest)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(auth_bp)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    response = client.get("/api/client/releases/beta.json")
    assert response.status_code == 200
    assert response.get_json() == manifest
    assert response.headers["Cache-Control"] == (
        "public, max-age=60"
    )
    assert response.headers["ETag"]

    cached = client.get(
        "/api/client/releases/beta.json",
        headers={"If-None-Match": response.headers["ETag"]},
    )
    assert cached.status_code == 304
    assert cached.data == b""
    assert cached.headers["ETag"] == response.headers["ETag"]


def test_server_refuses_unsigned_or_unknown_channel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    root.mkdir()
    (root / "beta.json").write_text(json.dumps({
        "schema_version": 1,
        "channel": "beta",
    }))
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    assert client.get("/api/client/releases/beta.json").status_code == 503
    assert client.get("/api/client/releases/stable.json").status_code == 404
    assert client.get("/api/client/releases/nightly.json").status_code == 404


def test_server_refuses_beta_manifest_without_digest_asset_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"beta")
    manifest = create_update_manifest(
        version="2.0.0-beta.1",
        build=8,
        channel="beta",
        dmg=dmg,
        dmg_url="http://127.0.0.1:8141/assets/FTClient.dmg",
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-21T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", manifest)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)

    assert app.test_client().get(
        "/api/client/releases/beta.json"
    ).status_code == 503


def test_server_serves_verified_retained_sha_addressed_beta_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    payload = b"verified beta installer"
    digest = sha256(payload).hexdigest()
    filename = f"{digest}.dmg"
    asset = root / "assets" / "beta" / filename
    asset.parent.mkdir(parents=True)
    asset.write_bytes(payload)
    manifest = create_update_manifest(
        version="2.0.0-beta.1",
        build=8,
        channel="beta",
        dmg=asset,
        dmg_url=(
            "http://127.0.0.1:8141/api/client/releases/assets/beta/"
            + filename
        ),
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-21T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", manifest)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    response = client.get(
        "/api/client/releases/assets/beta/" + filename
    )
    assert response.status_code == 200
    assert response.data == payload
    assert response.mimetype == "application/x-apple-diskimage"
    assert response.headers["Cache-Control"] == (
        "public, max-age=31536000, immutable"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    ranged = client.get(
        "/api/client/releases/assets/beta/" + filename,
        headers={"Range": "bytes=0-7"},
    )
    assert ranged.status_code == 206
    assert ranged.data == payload[:8]

    unreferenced = asset.with_name("0" * 64 + ".dmg")
    unreferenced.write_bytes(b"must stay private")
    assert client.get(
        "/api/client/releases/assets/beta/" + unreferenced.name
    ).status_code == 503
    assert client.get(
        "/api/client/releases/assets/beta/../private.dmg"
    ).status_code == 404

    replacement_payload = b"new beta"
    replacement_digest = sha256(replacement_payload).hexdigest()
    replacement = root / "assets" / "beta" / f"{replacement_digest}.dmg"
    replacement.write_bytes(replacement_payload)
    newer = create_update_manifest(
        version="2.0.0-beta.2",
        build=9,
        channel="beta",
        dmg=replacement,
        dmg_url=(
            "http://127.0.0.1:8141/api/client/releases/assets/beta/"
            + replacement.name
        ),
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-21T13:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", newer)
    assert client.get(
        "/api/client/releases/assets/beta/" + filename
    ).data == payload

    asset.unlink()
    asset.symlink_to(unreferenced)
    assert client.get(
        "/api/client/releases/assets/beta/" + filename
    ).status_code == 404
    asset.unlink()
    asset.write_bytes(payload)
    beta_root = root / "assets" / "beta"
    real_beta_root = root / "assets" / "beta-real"
    beta_root.rename(real_beta_root)
    beta_root.symlink_to(real_beta_root, target_is_directory=True)
    assert client.get(
        "/api/client/releases/assets/beta/" + filename
    ).status_code == 404
    beta_root.unlink()
    real_beta_root.rename(beta_root)
    assets_root = root / "assets"
    real_assets_root = root / "assets-real"
    assets_root.rename(real_assets_root)
    assets_root.symlink_to(real_assets_root, target_is_directory=True)
    assert client.get(
        "/api/client/releases/assets/beta/" + filename
    ).status_code == 404


def test_beta_manifest_to_dmg_works_over_real_loopback_http(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private, public = _keys(tmp_path / "keys")
    root = tmp_path / "channels"
    payload = b"network verified beta"
    digest = sha256(payload).hexdigest()
    asset = root / "assets" / "beta" / f"{digest}.dmg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(payload)
    monkeypatch.setattr(routes, "release_manifest_root", lambda: root)
    monkeypatch.setattr(
        routes, "trusted_release_public_key", lambda _channel: public
    )
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(auth_bp)
    app.register_blueprint(shared_bp)
    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    origin = f"http://127.0.0.1:{port}"
    manifest = create_update_manifest(
        version="2.0.0-beta.1",
        build=8,
        channel="beta",
        dmg=asset,
        dmg_url=(
            f"{origin}/api/client/releases/assets/beta/{asset.name}"
        ),
        minimum_client="1.2.0",
        mandatory=False,
        published_at="2026-07-21T12:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(root / "beta.json", manifest)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, validated, source = resolve_update_manifest(
            server_manifest_url=(
                f"{origin}/api/client/releases/beta.json"
            ),
            github_manifest_url="",
            channel="beta",
            public_key=public,
        )
        assert source == "server"
        with urlopen(validated.dmg_url, timeout=5) as response:
            downloaded = response.read()
        assert downloaded == payload
        assert sha256(downloaded).hexdigest() == validated.dmg_sha256
    finally:
        server.shutdown()
        thread.join(timeout=5)
