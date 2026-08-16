from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scripts.release.update_manifest import create_update_manifest, write_update_manifest
from tools.cli.release.client_release_targets import build_target_beta_package
from tools.cli.release.client_release_bundle import inspect_client_release_bundle

from tests.release.test_update_channel_manifest import _keys


def test_target_package_resigns_origin_for_each_manager(tmp_path: Path) -> None:
    private, public = _keys(tmp_path / "keys")
    release = tmp_path / "release"
    release.mkdir()
    dmg = release / "FactorTester-Client.dmg"
    dmg.write_bytes(b"installer")
    digest = sha256(dmg.read_bytes()).hexdigest()
    source_url = f"http://127.0.0.1:7998/api/client/releases/assets/beta/{digest}.dmg"
    manifest = create_update_manifest(
        version="0.1.3-beta.33",
        build=36,
        channel="beta",
        dmg=dmg,
        dmg_url=source_url,
        minimum_client="0.1.0",
        mandatory=False,
        published_at="2026-08-16T00:00:00Z",
        private_key=private,
        public_key=public,
    )
    write_update_manifest(release / "beta.json", manifest)
    (release / "appcast.xml").write_text(
        "<?xml version=\"1.0\"?><rss xmlns:sparkle=\"http://www.andymatuschak.org/xml-namespaces/sparkle\"><channel>"
        "<item><sparkle:version>36</sparkle:version>"
        "<sparkle:shortVersionString>0.1.3-beta.33</sparkle:shortVersionString>"
        "<sparkle:channel>beta</sparkle:channel>"
        f"<enclosure url=\"{source_url}\" sparkle:edSignature=\"signed\" /></item>"
        "</channel></rss>", encoding="utf-8",
    )
    package = tmp_path / "public.zip"
    build_target_beta_package(
        release,
        target_origin="https://public.example:7998",
        output=package,
        private_key=private,
        public_key=public,
    )
    inspected = inspect_client_release_bundle(package)
    assert inspected["version"] == "0.1.3-beta.33"
    import zipfile

    with zipfile.ZipFile(package) as archive:
        target_manifest = json.loads(archive.read("beta.json"))
        target_appcast = archive.read("beta.xml").decode()
    assert target_manifest["dmg_url"].startswith(
        "https://public.example:7998/api/client/releases/assets/beta/"
    )
    assert "https://public.example:7998/api/client/releases/assets/beta/" in target_appcast
