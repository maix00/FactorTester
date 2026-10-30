"""A cold visit loads one request per module group, not one per module.

Dozens of tiny script requests were the bulk of a cold page load on the
public uplink; each group is now served as one concatenated, compressed
response and the shell tags one bundle per initial group.
"""

from __future__ import annotations

import gzip
import json
from io import BytesIO
from urllib.parse import urlparse

import pytest

from server.manager.web import assets
from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.web.assets import (
    WEB_ROOT,
    bundle_bytes,
    bundle_bytes_for_groups,
    group_scripts,
    shell_bytes,
    static_file,
)


class _Handler:
    def __init__(self, accept_encoding="gzip"):
        self.headers = {"Accept-Encoding": accept_encoding}
        self.sent: list[tuple] = []
        self.status = None
        self.wfile = BytesIO()

    def _session(self):
        return None

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        self.sent.append(args)

    def end_headers(self):
        pass

    def header(self, name):
        return dict(self.sent).get(name)


class _BundleHandler(CoreGetRoutesMixin, _Handler):
    """The entry route itself is exercised; only the login gate is stubbed."""

    def _public_login_gate(self, parsed, *, method="GET"):
        return True

    def _redirect_configured_ingress(self, parsed, *, next_path="/"):
        return False

    def _reject_retired_local_identity_route(self, parsed):
        return False

    def send_error(self, status, *args, **kwargs):
        self.status = status

    def __getattr__(self, name):
        if name.startswith("_get_") or name.endswith("_get"):
            return lambda *args, **kwargs: False
        raise AttributeError(name)


def _manifest() -> dict:
    return json.loads((WEB_ROOT / "module-manifest.json").read_text())


def test_bundle_concatenates_the_group_in_declared_order():
    scripts = group_scripts("report")
    assert len(scripts) > 1
    parts = [static_file(relative)[0] for relative in scripts]
    assert bundle_bytes("report") == b"\n;\n".join(parts)
    # A group the manifest does not declare is never guessed.
    with pytest.raises(ValueError):
        bundle_bytes("not-a-group")


def test_bundle_cache_keeps_sibling_groups_for_the_same_revision(monkeypatch):
    assets._bundle_cache.clear()
    monkeypatch.setattr(assets, "_bundle_cache_revision", None)
    monkeypatch.setattr(assets, "asset_revision", lambda: "revision-1")
    monkeypatch.setattr(assets, "group_scripts", lambda group: [f"{group}.js"])
    reads = []

    def read_asset(relative):
        reads.append(relative)
        return relative.encode(), "application/javascript"

    monkeypatch.setattr(assets, "static_file", read_asset)

    assert assets.bundle_bytes("first") == b"first.js"
    assert assets.bundle_bytes("second") == b"second.js"
    assert assets.bundle_bytes("first") == b"first.js"
    assert reads == ["first.js", "second.js"]


def test_bundle_cache_discards_groups_when_revision_changes(monkeypatch):
    assets._bundle_cache.clear()
    monkeypatch.setattr(assets, "_bundle_cache_revision", None)
    revision = ["revision-1"]
    monkeypatch.setattr(assets, "asset_revision", lambda: revision[0])
    monkeypatch.setattr(assets, "group_scripts", lambda group: [f"{group}.js"])
    monkeypatch.setattr(
        assets,
        "static_file",
        lambda relative: (relative.encode(), "application/javascript"),
    )

    assets.bundle_bytes("first")
    assets.bundle_bytes("second")
    assert set(assets._bundle_cache) == {
        ("first", "revision-1"),
        ("second", "revision-1"),
    }

    revision[0] = "revision-2"
    assets.bundle_bytes("first")
    assert set(assets._bundle_cache) == {("first", "revision-2")}


def test_group_set_bundle_cache_is_bounded(monkeypatch):
    assets._bundle_cache.clear()
    assets._bundle_set_cache.clear()
    monkeypatch.setattr(assets, "_bundle_cache_revision", None)
    monkeypatch.setattr(assets, "asset_revision", lambda: "revision-1")
    monkeypatch.setattr(
        assets,
        "_module_manifest",
        lambda: {"groups": {f"g{index}": [f"g{index}.js"] for index in range(6)}},
    )
    monkeypatch.setattr(
        assets,
        "static_file",
        lambda relative: (relative.encode(), "application/javascript"),
    )

    names = [f"g{index}" for index in range(6)]
    for mask in range(1, 1 << len(names)):
        assets.bundle_bytes_for_groups([
            name for index, name in enumerate(names) if mask & (1 << index)
        ])

    assert len(assets._bundle_set_cache) == assets._MAX_BUNDLE_SET_CACHE_ENTRIES


def test_bundle_route_serves_compressed_javascript():
    handler = _BundleHandler("gzip")
    assert handler._get_entry_routes(urlparse("/research-static/__group__/report"))
    assert handler.status == 200
    assert handler.header("Content-Type") == "application/javascript; charset=utf-8"
    assert handler.header("Content-Encoding") == "gzip"
    assert handler.header("Vary") == "Accept-Encoding"
    assert handler.header("Cache-Control") == "public, max-age=31536000, immutable"
    assert gzip.decompress(handler.wfile.getvalue()) == bundle_bytes("report")


def test_bundle_route_keeps_a_plain_body_without_accept_encoding():
    handler = _BundleHandler("")
    assert handler._get_entry_routes(urlparse("/research-static/__group__/report"))
    assert handler.header("Content-Encoding") is None
    assert handler.wfile.getvalue() == bundle_bytes("report")


def test_bundle_route_rejects_an_unknown_group():
    handler = _BundleHandler("gzip")
    assert handler._get_entry_routes(urlparse("/research-static/__group__/nope"))
    assert handler.status == 404


def test_group_set_bundle_route_serves_ordered_group_closure():
    names = ["code-viewer", "report"]
    expected = bundle_bytes_for_groups(names)
    handler = _BundleHandler("gzip")
    assert handler._get_entry_routes(
        urlparse("/research-static/__groups__/" + ",".join(names)),
    )
    assert handler.status == 200
    assert handler.header("Content-Type") == "application/javascript; charset=utf-8"
    assert handler.header("Content-Encoding") == "gzip"
    assert gzip.decompress(handler.wfile.getvalue()) == expected


def test_group_set_bundle_route_rejects_an_undeclared_group():
    handler = _BundleHandler("gzip")
    assert handler._get_entry_routes(
        urlparse("/research-static/__groups__/core,not-a-group"),
    )
    assert handler.status == 404


def test_shell_uses_one_ordered_initial_bundle_when_supported():
    manifest = _manifest()
    html = shell_bytes().decode("utf-8")
    initial = [str(item) for item in manifest["initial_groups"]]
    assert initial
    if manifest.get("group_set_bundles") is True:
        assert f'"/research-static/__groups__/{",".join(initial)}?v=' in html
        for name in initial:
            for relative in manifest["groups"][name]:
                assert f'"/research-static/{relative}?v=' not in html
    else:
        assert "__groups__" not in html
        for name in initial:
            for relative in manifest["groups"][name]:
                assert f'"/research-static/{relative}?v=' in html


def test_lazy_groups_are_bundled_but_still_declared():
    """Every lazy group has a bundle; the declared files stay the fallback."""
    manifest = _manifest()
    initial = {str(item) for item in manifest["initial_groups"]}
    assert manifest.get("group_bundles") is True
    for name, files in manifest["groups"].items():
        if name in initial or not files:
            continue
        assert bundle_bytes(name) == b"\n;\n".join(
            static_file(relative)[0] for relative in files
        )


def test_react_shell_assets_are_served_and_manifest_gated():
    from server.manager.web.assets import static_file

    html, kind = static_file("vendor/web-app/index.html")
    assert b"data-tr-web-app" in html
    assert b"/research-static/vendor/web-app/loader.js" in html
    assert b"/research-static/styles/app.css" in html
    assert kind.startswith("text/html")
    for name in ("loader.js", "desktop.js", "desktop.css", "mobile.js", "mobile.css"):
        body, content_type = static_file(f"vendor/web-app/{name}")
        assert body
        assert content_type
    sw, sw_type = static_file("sw.js")
    assert b"tr-shell-" in sw
    assert b"/research-static/vendor/web-app/desktop.js" in sw
    assert "javascript" in sw_type
    manifest, manifest_type = static_file("vendor/web-app/manifest.webmanifest")
    assert json.loads(manifest)["start_url"] == "/app"
    assert manifest_type == "application/manifest+json"


def test_react_shell_and_lazy_assets_share_declared_content_versions():
    import html
    import re
    versions = assets.web_app_asset_versions()
    for name in ["loader.js", "desktop.js", "desktop.css", "configuration-code.js", "configuration-code.css", "configuration-editor-worker.js", "configuration-json-worker.js", "artifact-frame.js"]:
        assert versions[name]
        assert static_file("vendor/web-app/" + name)[0]
    body = assets.web_app_shell_bytes().decode()
    assert f'loader.js?v={versions["loader.js"]}' in body
    data = re.search(r'data-tr-asset-versions="([^"]+)"', body).group(1)
    assert json.loads(html.unescape(data)) == versions
    assert f'artifact-frame.js?v={versions["artifact-frame.js"]}' in assets.web_app_frame_bytes().decode()


def test_react_versions_reuse_unchanged_files_when_one_asset_changes(tmp_path, monkeypatch):
    root = tmp_path / "web-app"; root.mkdir()
    for name in ["desktop.js", "configuration-code.js"]:
        (root / name).write_text(name)
    monkeypatch.setattr(assets, "VENDOR_ROOT", tmp_path)
    monkeypatch.setattr(assets, "_module_manifest", lambda: {"vendor_assets": ["vendor/web-app/desktop.js", "vendor/web-app/configuration-code.js"]})
    assets._web_app_digest.cache_clear()
    first = assets.web_app_asset_versions()
    before = assets._web_app_digest.cache_info()
    assert assets.web_app_asset_versions() == first
    assert assets._web_app_digest.cache_info().misses == before.misses
    (root / "desktop.js").write_text("changed desktop")
    second = assets.web_app_asset_versions()
    assert first["desktop.js"] != second["desktop.js"]
    assert first["configuration-code.js"] == second["configuration-code.js"]
    assert assets._web_app_digest.cache_info().misses == before.misses + 1


def test_react_unversioned_assets_revalidate_but_versioned_assets_reuse_cache():
    for name in ["desktop.css", "configuration-code.js", "configuration-json-worker.js", "artifact-frame.js"]:
        path = "/research-static/vendor/web-app/" + name
        handler = _BundleHandler("")
        assert handler._get_entry_routes(urlparse(path))
        assert handler.status == 200
        assert handler.header("Cache-Control") == "no-cache"
        handler = _BundleHandler("")
        assert handler._get_entry_routes(urlparse(path + "?v=" + assets.web_app_asset_versions()[name]))
        assert handler.header("Cache-Control") == "public, max-age=31536000, immutable"
