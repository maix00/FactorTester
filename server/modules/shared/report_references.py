"""Resolve canonical report links from server-registered domain objects."""

from __future__ import annotations

from flask import request

from server.services.api_response import api_ok, route_guard
from server.services.http_auth import login_required
from server.services.report_reference_resolution import (
    resolve_report_reference,
)

from . import shared_bp
from .price_services import cached_contracts, cached_products


@shared_bp.get("/api/report-references/resolve")
@login_required
@route_guard
def resolve_report_reference_route():
    reference = resolve_report_reference(
        kind=str(request.args.get("kind") or ""),
        target=str(request.args.get("target") or ""),
        products=cached_products(),
        contracts=cached_contracts(),
    )
    return api_ok({"reference": reference})
