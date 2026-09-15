"""Manager responses are compressed so a slow uplink carries what it must.

The factor library list alone is close to a megabyte of JSON and a cold visit
pulls dozens of module files; both are read over a public uplink, so the
compression decision is shared by the JSON routes, the proxy pass-through and
static modules.
"""

from __future__ import annotations

import gzip
import json
from io import BytesIO
from urllib.parse import urlparse

from server.manager.http.content_encoding import (
    accepts_gzip,
    encode_body,
    is_compressible,
)
from server.manager.http.core_get_routes import CoreGetRoutesMixin
from server.manager.http.responses import json_response


class _Handler:
    def __init__(self, accept_encoding="gzip"):
        self.headers = {"Accept-Encoding": accept_encoding}
        self.sent: list[tuple] = []
        self.status = None
        self.wfile = BytesIO()

    def _session(self):
        return None

    def _bearer_token(self):
        return ""

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        self.sent.append(args)

    def end_headers(self):
        pass

    def header(self, name):
        return dict(self.sent).get(name)


class _StaticHandler(CoreGetRoutesMixin, _Handler):
    """The entry route itself is exercised; only the login gate is stubbed."""

    def _public_login_gate(self, parsed, *, method="GET"):
        return True

    def __getattr__(self, name):
        # The entry route chains through sibling mixins; only the static branch
        # is under test, so an unhandled sibling route simply continues.
        if name.startswith("_get_") or name.endswith("_get"):
            return lambda *args, **kwargs: False
        raise AttributeError(name)

    def _redirect_configured_ingress(self, parsed, *, next_path="/"):
        return False

    def _serve_login_page(self, parsed):
        return None


def test_accepts_gzip_parses_the_header():
    assert accepts_gzip("gzip") is True
    assert accepts_gzip("br, gzip;q=0.8") is True
    assert accepts_gzip("gzip;q=0") is False
    assert accepts_gzip("br, deflate") is False
    assert accepts_gzip("") is False


def test_encode_body_only_compresses_worthwhile_text():
    payload = json.dumps({"value": "x" * 4000}).encode("utf-8")
    encoded, gzipped = encode_body(payload, "application/json", "gzip")
    assert gzipped is True
    assert len(encoded) < len(payload)
    assert gzip.decompress(encoded) == payload
    # Too small to be worth the framing cost.
    small, gzipped_small = encode_body(b"{}", "application/json", "gzip")
    assert small == b"{}" and gzipped_small is False
    # Binary or already-compressed payloads are never re-encoded.
    assert encode_body(payload, "image/png", "gzip")[1] is False
    assert encode_body(payload, "application/pdf", "gzip")[1] is False
    # A client that did not ask for gzip gets the plain body.
    assert encode_body(payload, "application/json", "")[1] is False
    assert is_compressible("text/markdown; charset=utf-8") is True


def test_json_response_is_gzipped_when_the_client_accepts_it():
    handler = _Handler("gzip")
    json_response(handler, {"families": ["x" * 2000]})
    assert handler.header("Content-Encoding") == "gzip"
    assert handler.header("Vary") == "Accept-Encoding"
    assert gzip.decompress(handler.wfile.getvalue()) == json.dumps(
        {"families": ["x" * 2000]}, ensure_ascii=False,
    ).encode("utf-8")


def test_json_response_stays_plain_without_accept_encoding():
    handler = _Handler("")
    json_response(handler, {"ok": True})
    assert handler.header("Content-Encoding") is None
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == {"ok": True}


def test_static_module_is_gzipped_and_keeps_its_cache_policy():
    handler = _StaticHandler("gzip")
    assert handler._get_entry_routes(urlparse("/research-static/app/runtime.js"))
    assert handler.status == 200
    assert handler.header("Content-Encoding") == "gzip"
    assert handler.header("Cache-Control") == "public, max-age=31536000, immutable"
    body = gzip.decompress(handler.wfile.getvalue())
    assert b"runtime" in body or b"() =>" in body or b"function" in body


def test_static_module_shell_is_not_cached_but_is_compressed():
    handler = _StaticHandler("gzip")
    assert handler._get_entry_routes(urlparse("/research-static/research.html"))
    assert handler.status == 200
    assert handler.header("Cache-Control") == "no-store"
    assert handler.header("Content-Encoding") == "gzip"
