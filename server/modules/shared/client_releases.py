"""Public cacheable signed client-release channel metadata."""

from __future__ import annotations

from importlib.resources import files
import os
from pathlib import Path

from flask import Response, current_app, request

from server.services.client_release_channels import (
    load_client_release_channel,
)

from . import shared_bp


def release_manifest_root() -> Path:
    configured = os.environ.get("FACTORTESTER_RELEASE_MANIFEST_ROOT", "")
    return Path(configured).expanduser() if configured else Path(
        current_app.instance_path
    ) / "client-releases"


def trusted_release_public_key() -> Path:
    return Path(str(
        files("tools.cli.release").joinpath("trusted-release-public.pem")
    ))


@shared_bp.get("/api/client/releases/<channel>.json")
def client_release_channel(channel: str):
    try:
        raw, etag = load_client_release_channel(
            release_manifest_root(),
            channel,
            public_key=trusted_release_public_key(),
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
    response.headers["Cache-Control"] = (
        "public, max-age=300, stale-if-error=86400"
    )
    return response
