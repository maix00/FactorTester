from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from scripts.release.update_manifest import create_update_manifest, write_update_manifest
from server.manager.objects.adapters.client_release import ClientReleaseDestinationAdapter
from server.manager import runtime as manager
from tools.cli.release.client_release_bundle import build_client_release_bundle

from tests.release.test_update_channel_manifest import _keys


def test_uploaded_beta_bundle_is_verified_and_activated(tmp_path: Path) -> None:
    private, public = _keys(tmp_path / "keys")
    dmg = tmp_path / "FTClient.dmg"
    dmg.write_bytes(b"beta installer")
    digest = sha256(dmg.read_bytes()).hexdigest()
    origin = "https://factor.example"
    dmg_url = f"{origin}/api/client/releases/assets/beta/{digest}.dmg"
    manifest = create_update_manifest(
        version="0.1.3-beta.33",
        build=36,
        channel="beta",
        dmg=dmg,
        dmg_url=dmg_url,
        minimum_client="0.1.0",
        mandatory=False,
        published_at="2026-08-16T00:00:00Z",
        private_key=private,
        public_key=public,
    )
    manifest_path = tmp_path / "beta.json"
    write_update_manifest(manifest_path, manifest)
    appcast_path = tmp_path / "beta.xml"
    appcast_path.write_text(
        "<?xml version=\"1.0\"?><rss xmlns:sparkle=\"http://www.andymatuschak.org/xml-namespaces/sparkle\"><channel>"
        "<item><sparkle:version>36</sparkle:version>"
        "<sparkle:shortVersionString>0.1.3-beta.33</sparkle:shortVersionString>"
        "<sparkle:channel>beta</sparkle:channel>"
        f"<enclosure url=\"{dmg_url}\" sparkle:edSignature=\"signed\" /></item>"
        "</channel></rss>",
        encoding="utf-8",
    )
    package = tmp_path / "release.zip"
    build_client_release_bundle(
        dmg=dmg,
        appcast=appcast_path,
        manifest=manifest_path,
        output=package,
    )
    release_root = tmp_path / "client-releases"
    adapter = ClientReleaseDestinationAdapter(
        release_root=release_root,
        public_key=public,
    )
    transfer = SimpleNamespace(
        object_kind="client_release",
        object_id=f"beta:0.1.3-beta.33:36:{sha256(package.read_bytes()).hexdigest()}",
        principal="GTHT@MaxJJW@1234",
        expected_size=package.stat().st_size,
        expected_sha256=sha256(package.read_bytes()).hexdigest(),
    )
    staged = tmp_path / "staged.zip"
    staged.write_bytes(package.read_bytes())
    result = adapter(SimpleNamespace(transfer=transfer), staged)

    assert result == (release_root / "beta.json").resolve()
    assert not staged.exists()
    assert (release_root / "beta.json").is_file()
    assert (release_root / "beta.xml").is_file()
    assert (release_root / "assets/beta" / f"{digest}.dmg").read_bytes() == dmg.read_bytes()


def test_release_upload_access_requires_manager_session(tmp_path: Path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="local")
    state.prepare_object_upload = lambda **kwargs: {
        "url": "http://127.0.0.1:7997/v1/transfers/a/upload",
        "bearer": "short-lived",
        **kwargs,
    }
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({
            "version": "0.1.3-beta.33",
            "build": 36,
            "package_size_bytes": 4,
            "package_sha256": "a" * 64,
        }).encode()
        denied = Request(
            f"http://127.0.0.1:{server.server_port}/api/client/releases/beta/upload-access",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(denied)
        except Exception as exc:
            assert getattr(exc, "code", None) == 403

        token, _, _ = state._issue_session("GTHT@MaxJJW@1234", "super_admin")
        allowed = Request(
            denied.full_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urlopen(allowed) as response:
            payload = json.loads(response.read())
        assert payload["success"] is True
        assert payload["release"]["build"] == 36
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
