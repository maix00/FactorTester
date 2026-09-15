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

from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.web.assets import (
    WEB_ROOT,
    bundle_bytes,
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

    def _serve_login_page(self, parsed):
        return None

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


def test_shell_keeps_individual_initial_tags():
    """First paint stays on the proven per-file path."""
    manifest = _manifest()
    html = shell_bytes().decode("utf-8")
    initial = [str(item) for item in manifest["initial_groups"]]
    assert initial
    assert "__group__" not in html
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
