"""Signed FTClient release channel and content-addressed asset routes."""

from __future__ import annotations

import hashlib
import re

from server.manager.http.responses import json_response
from server.services.client_release_channels import (
    load_beta_sparkle_appcast,
    load_client_release_channel,
)


class ClientReleaseRoutesMixin:
    """Serve verified release metadata and immutable ranged downloads."""
    def _serve_client_release(self, path: str) -> bool:
        public_key = (
            self.state.runtime_source_root
            / "tools/cli/release/trusted-beta-release-public.pem"
        )
        try:
            if path == "/api/client/releases/beta.json":
                raw, etag = load_client_release_channel(
                    self.state.release_root, "beta", public_key=public_key,
                )
                self._release_bytes(raw, "application/json", etag)
                return True
            if path == "/api/client/releases/beta.xml":
                raw, etag = load_beta_sparkle_appcast(
                    self.state.release_root, public_key=public_key,
                )
                self._release_bytes(raw, "application/rss+xml", etag)
                return True
            match = re.fullmatch(
                r"/api/client/releases/assets/beta/([0-9a-f]{64})\.(dmg|delta)",
                path,
            )
            if match:
                self._release_asset(match.group(1), match.group(2))
                return True
        except FileNotFoundError:
            json_response(self, {"success": False, "error": "release not found"}, 404)
            return True
        except (OSError, ValueError):
            json_response(self, {"success": False, "error": "release unavailable"}, 503)
            return True
        return False

    def _release_bytes(self, raw: bytes, content_type: str, etag: str) -> None:
        if self.headers.get("If-None-Match", "").strip('"') == etag:
            self.send_response(304)
            self.send_header("ETag", f'"{etag}"')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _release_asset(self, digest: str, suffix: str) -> None:
        asset = self.state.release_root / "assets/beta" / f"{digest}.{suffix}"
        resolved = asset.resolve(strict=True)
        expected_parent = (self.state.release_root / "assets/beta").resolve()
        if resolved.parent != expected_parent or not resolved.is_file():
            raise FileNotFoundError(asset)
        hasher = hashlib.sha256()
        with resolved.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ValueError("release asset digest mismatch")
        size = resolved.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range", "")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2) or end)
            else:
                length = int(match.group(2))
                start = max(0, size - length)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("ETag", f'"{digest}"')
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with resolved.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
