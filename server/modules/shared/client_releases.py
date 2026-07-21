"""Public cacheable signed client-release channel metadata."""

from __future__ import annotations

import errno
from importlib.resources import files
import os
from pathlib import Path
import re
from hashlib import sha256
import stat

from flask import Response, current_app, request

from server.services.client_release_channels import (
    load_client_release_channel,
)

from . import shared_bp


_ASSET_NAME = re.compile(r"^[0-9a-f]{64}\.dmg$")
_MAX_DMG_BYTES = 4 * 1024 * 1024 * 1024


def release_manifest_root() -> Path:
    configured = os.environ.get("FACTORTESTER_RELEASE_MANIFEST_ROOT", "")
    return Path(configured).expanduser() if configured else Path(
        current_app.instance_path
    ) / "client-releases"


def trusted_release_public_key(channel: str) -> Path:
    if channel != "beta":
        raise ValueError("server release channel is not Beta")
    return Path(str(
        files("tools.cli.release").joinpath(
            "trusted-beta-release-public.pem"
        )
    ))


@shared_bp.get("/api/client/releases/<channel>.json")
def client_release_channel(channel: str):
    if channel != "beta":
        return {"success": False, "error": "release channel not found"}, 404
    try:
        raw, etag = load_client_release_channel(
            release_manifest_root(),
            channel,
            public_key=trusted_release_public_key(channel),
        )
    except FileNotFoundError:
        return {"success": False, "error": "release channel not found"}, 404
    except (OSError, ValueError):
        current_app.logger.exception("invalid client release channel")
        return {"success": False, "error": "release channel unavailable"}, 503
    if request.if_none_match.contains(etag):
        response = Response(status=304)
    else:
        response = Response(raw, content_type="application/json")
    response.set_etag(etag, weak=False)
    response.headers["Cache-Control"] = "public, max-age=60"
    return response


@shared_bp.get("/api/client/releases/assets/<channel>/<filename>")
def client_release_asset(channel: str, filename: str):
    """Serve one retained, SHA-addressed Beta DMG without path re-resolution."""
    if channel != "beta" or not _ASSET_NAME.fullmatch(filename):
        return {"success": False, "error": "release asset not found"}, 404
    handle = None
    directory_descriptors: list[int] = []
    try:
        root = release_manifest_root().resolve()
        expected_digest = filename.removesuffix(".dmg")
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_descriptors.append(os.open(root, directory_flags))
        for component in ("assets", channel):
            directory_descriptors.append(os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptors[-1],
            ))
        descriptor = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_descriptors[-1],
        )
        handle = os.fdopen(descriptor, "rb")
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _MAX_DMG_BYTES
            or _stream_sha256(handle) != expected_digest
        ):
            handle.close()
            return {"success": False, "error": "release asset unavailable"}, 503
        handle.seek(0)
    except (OSError, ValueError) as exc:
        if handle is not None:
            handle.close()
        missing_or_link = isinstance(exc, OSError) and exc.errno in {
            errno.ENOENT, errno.ENOTDIR, errno.ELOOP,
        }
        current_app.logger.exception("invalid client release asset")
        status_code = 404 if missing_or_link else 503
        return {
            "success": False,
            "error": (
                "release asset not found"
                if missing_or_link else "release asset unavailable"
            ),
        }, status_code
    finally:
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
    if request.if_none_match.contains(expected_digest):
        handle.close()
        response = Response(status=304)
        response.set_etag(expected_digest, weak=False)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
        )
        return response
    start, stop, status_code = 0, metadata.st_size, 200
    requested_range = request.range
    if requested_range is not None:
        bounds = (
            requested_range.range_for_length(metadata.st_size)
            if requested_range.units == "bytes"
            and len(requested_range.ranges) == 1
            else None
        )
        if bounds is None:
            handle.close()
            response = Response(status=416)
            response.headers["Content-Range"] = f"bytes */{metadata.st_size}"
            return response
        start, stop = bounds
        status_code = 206
        handle.seek(start)
    response = Response(
        _bounded_stream(handle, stop - start),
        status=status_code,
        content_type="application/x-apple-diskimage",
    )
    response.call_on_close(handle.close)
    response.content_length = stop - start
    response.set_etag(expected_digest, weak=False)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    if status_code == 206:
        response.headers["Content-Range"] = (
            f"bytes {start}-{stop - 1}/{metadata.st_size}"
        )
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _stream_sha256(handle) -> str:
    digest = sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _bounded_stream(handle, remaining: int):
    while remaining:
        chunk = handle.read(min(1024 * 1024, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk
