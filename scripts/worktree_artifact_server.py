#!/usr/bin/env python3
"""Serve retained FactorTester artifacts on the 7997 data-plane port."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import mimetypes
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.jobs.artifact_data_plane import (  # noqa: E402
    ArtifactTicketCodec,
    ArtifactTicketError,
    artifact_data_port,
)
from server.jobs.artifacts import resolve_artifact_path  # noqa: E402
from server.jobs.repository import JobRepository  # noqa: E402
from server.manager.http.security import (  # noqa: E402
    configured_tls_paths,
    enable_server_tls,
    server_tls_context,
)


_ARTIFACT_PATH = re.compile(
    r"^/v1/artifacts/([A-Za-z0-9._-]{1,128})/([^/]{1,256})$"
)


@dataclass(frozen=True)
class ArtifactDataConfig:
    server_id: str


class ArtifactDataHandler(BaseHTTPRequestHandler):
    server: "ArtifactDataHTTPServer"

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps(
            {"success": False, "error": str(message)},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _artifact(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            body = json.dumps({
                "success": True,
                "service": "artifact-data",
                "port": self.server.server_port,
            }, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        match = _ARTIFACT_PATH.fullmatch(parsed.path)
        if match is None:
            self._json_error(404, "artifact data route not found")
            return
        job_id = unquote(match.group(1))
        name = unquote(match.group(2))
        ticket_name = "__archive__" if name == "archive" else name
        ticket = str(parse_qs(parsed.query).get("ticket", [""])[0] or "")
        try:
            claims = self.server.codec.verify(
                ticket,
                job_id=job_id,
                name=ticket_name,
                server_id=self.server.config.server_id,
            )
        except ArtifactTicketError as exc:
            self._json_error(403, str(exc))
            return
        owner = str(claims.get("owner") or "").strip()
        if not owner:
            self._json_error(403, "artifact ticket has no owner")
            return
        if ticket_name == "__archive__":
            try:
                raw = self._archive_bytes(job_id=job_id, owner=owner)
            except FileNotFoundError:
                self._json_error(410, "artifact file is unavailable")
                return
            except RuntimeError:
                self._json_error(500, "artifact integrity check failed")
                return
            self._send_bytes(
                raw,
                content_type="application/zip",
                file_name=f"job-{job_id}-artifacts.zip",
                etag=None,
            )
            return
        metadata = self.server.repository.load_artifact(
            job_id=job_id,
            name=name,
            owner=owner,
        )
        if metadata is None:
            self._json_error(404, "artifact not found")
            return
        if str(metadata.get("state") or "") != "active":
            self._json_error(410, "artifact was deleted")
            return
        try:
            path = resolve_artifact_path(
                str(metadata["relative_path"]),
                expected_hash=str(metadata["content_hash"]),
            )
            size = int(path.stat().st_size)
        except (FileNotFoundError, OSError):
            self._json_error(410, "artifact file is unavailable")
            return
        except RuntimeError:
            self._json_error(500, "artifact integrity check failed")
            return
        if size != max(0, int(metadata.get("size_bytes") or 0)):
            self._json_error(500, "artifact size metadata mismatch")
            return
        start, end, status = self._range(size)
        if start is None:
            return
        content_type = str(metadata.get("content_type") or "").strip()
        if not content_type:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file_name = Path(str(metadata.get("file_name") or path.name)).name or path.name
        disposition = "inline" if bool(claims.get("preview")) else "attachment"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'{disposition}; filename="{file_name}"')
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", f'"{metadata["content_hash"]}"')
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors_headers()
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _range(self, size: int) -> tuple[int | None, int | None, int]:
        if size <= 0:
            return 0, -1, 200
        header = str(self.headers.get("Range") or "").strip()
        if not header:
            return 0, size - 1, 200
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
        if match is None or (not match.group(1) and not match.group(2)):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self._cors_headers()
            self.end_headers()
            return None, None, 416
        try:
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2) or size - 1)
            else:
                suffix = int(match.group(2))
                start = max(0, size - suffix)
                end = size - 1
        except ValueError:
            start, end = 1, 0
        if start < 0 or start >= size or end < start:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self._cors_headers()
            self.end_headers()
            return None, None, 416
        return start, min(end, size - 1), 206

    def _archive_bytes(self, *, job_id: str, owner: str) -> bytes:
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for metadata in self.server.repository.list_artifacts(
                job_id=job_id, owner=owner,
            ):
                if str(metadata.get("state") or "") != "active":
                    continue
                path = resolve_artifact_path(
                    str(metadata["relative_path"]),
                    expected_hash=str(metadata["content_hash"]),
                )
                file_name = Path(str(metadata.get("file_name") or path.name)).name
                if not file_name:
                    file_name = path.name
                if str(metadata.get("artifact_role") or "output") == "input":
                    kind = re.sub(
                        r"[^A-Za-z0-9_-]+", "-",
                        str(metadata.get("artifact_kind") or "input"),
                    ).strip("-") or "input"
                    member = f"inputs/{kind}/{file_name}"
                else:
                    member = file_name
                bundle.writestr(member, path.read_bytes())
        return archive.getvalue()

    def _send_bytes(
        self,
        raw: bytes,
        *,
        content_type: str,
        file_name: str,
        etag: str | None,
    ) -> None:
        start, end, status = self._range(len(raw))
        if start is None:
            return
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{file_name}"')
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        if etag:
            self.send_header("ETag", f'"{etag}"')
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors_headers()
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(raw)}")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw[start:end + 1])

    def do_GET(self) -> None:  # noqa: N802
        self._artifact()

    def do_HEAD(self) -> None:  # noqa: N802
        self._artifact()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors_headers(self) -> None:
        origin = str(self.headers.get("Origin") or "").strip()
        self.send_header("Access-Control-Allow-Origin", origin or "*")
        if origin:
            self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Expose-Headers",
            "Accept-Ranges, Content-Disposition, Content-Length, Content-Range, ETag",
        )

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[artifact-data] " + (fmt % args) + "\n")


class ArtifactDataHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address, handler, *, server_id: str):
        super().__init__(address, handler)
        self.codec = ArtifactTicketCodec()
        self.repository = JobRepository()
        self.config = ArtifactDataConfig(server_id=str(server_id or ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=artifact_data_port())
    parser.add_argument(
        "--server-id",
        default=os.environ.get("FACTORTESTER_SERVER_ID", "local"),
    )
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    args = parser.parse_args()
    tls_paths = configured_tls_paths(
        args.tls_cert,
        args.tls_key,
        certificate_env="FACTORTESTER_ARTIFACT_TLS_CERT",
        private_key_env="FACTORTESTER_ARTIFACT_TLS_KEY",
    )
    server = ArtifactDataHTTPServer(
        (args.host, artifact_data_port(args.port)),
        ArtifactDataHandler,
        server_id=args.server_id,
    )
    if tls_paths is not None:
        enable_server_tls(server, server_tls_context(*tls_paths))
    print(
        f"FactorTester artifact data service running on {args.host}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
