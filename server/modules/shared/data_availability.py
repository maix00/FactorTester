"""HTTP boundary for compact market-data availability inspection."""

from __future__ import annotations

from flask import jsonify, request

from server.services.data_availability import (
    availability_for_scope,
    data_capability_catalog,
    load_availability_profile,
    profile_reference,
)
from tools.data.availability.model import PROFILE_SCHEMA_VERSION

from . import shared_bp


@shared_bp.post("/api/data-availability")
def data_availability():
    payload = request.get_json(silent=True) or {}
    products = _string_list(payload.get("products"))
    sources = _string_list(payload.get("sources"))
    if not products:
        return jsonify(success=False, error="必须明确提供 products 范围"), 400
    if not sources:
        return jsonify(success=False, error="必须明确提供 sources 范围"), 400
    try:
        profile = availability_for_scope(
            product_names=products,
            source_names=sources,
            frequency_names=_string_list(payload.get("frequencies")),
            probe=bool(payload.get("probe", False)),
            expanded=bool(payload.get("expanded", False)),
            required_fields=_string_list(payload.get("fields")),
            include_field_catalog=bool(payload.get("include_field_catalog", False)),
            include_historical_fields=bool(payload.get("include_historical_fields", False)),
        )
    except LookupError as exc:
        return jsonify(success=False, error=str(exc)), 404
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(
        success=True,
        profile_ref=profile_reference(profile),
        profile_identity_semantics=_profile_identity_semantics(profile),
        profile_identity_notice=_profile_identity_notice(profile),
        **profile,
    )


@shared_bp.get("/api/data-capabilities")
def data_capabilities():
    """List declared sources and frozen coverage without scanning files."""
    return jsonify(success=True, catalog=data_capability_catalog())


@shared_bp.get("/api/data-availability/profiles/<path:profile_ref>")
def data_availability_profile(profile_ref: str):
    try:
        profile = load_availability_profile(profile_ref)
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    except KeyError as exc:
        return jsonify(success=False, error=str(exc)), 404
    return jsonify(
        success=True,
        profile_ref=profile_ref,
        profile_identity_semantics=_profile_identity_semantics(profile),
        profile_identity_notice=_profile_identity_notice(profile),
        **profile,
    )


def _profile_identity_semantics(profile: dict) -> str:
    version = int(profile.get("schema_version") or 0)
    if version >= PROFILE_SCHEMA_VERSION:
        return "source_key_current_source_contents"
    return "legacy_metadata_only"


def _profile_identity_notice(profile: dict) -> str:
    version = int(profile.get("schema_version") or 0)
    if version >= PROFILE_SCHEMA_VERSION:
        return (
            "This profile records source identity and observed coverage; it does "
            "not pin market-data bytes. Source contents and their updates are "
            "managed by the data source."
        )
    return (
        "Legacy profile metadata does not pin market-data bytes. Its snapshot_ref "
        "is only a file-metadata marker, and replayable=true does not guarantee "
        "byte-identical replay. Source contents and updates remain source-managed."
    )


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
