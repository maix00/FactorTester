from __future__ import annotations

import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from server.manager.http.client_release_routes import ClientReleaseRoutesMixin
from server.manager.http.core_get_routes import CoreGetRoutesMixin


def test_manager_serves_beta_asset_head_without_body(tmp_path: Path) -> None:
    payload = b"signed beta installer"
    digest = sha256(payload).hexdigest()
    release_root = tmp_path / "releases"
    asset = release_root / "assets" / "beta" / f"{digest}.dmg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(payload)

    class Handler(
        ClientReleaseRoutesMixin,
        CoreGetRoutesMixin,
        BaseHTTPRequestHandler,
    ):
        state = SimpleNamespace(
            release_root=release_root,
            runtime_source_root=tmp_path,
        )

        def _redirect_plain_http_to_https(self) -> bool:
            return False

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}"
            f"/api/client/releases/assets/beta/{digest}.dmg",
            method="HEAD",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(payload))
            assert response.headers["Accept-Ranges"] == "bytes"
            assert response.headers["ETag"] == f'"{digest}"'
            assert response.read() == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
