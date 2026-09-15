"""One stale registration must not fail the whole client library projection.

A config frozen before its family's formula changed keeps a factor reference
that no longer matches its identity.  That used to raise out of the projection
builder, so every caller got a 400 and could not read any factor at all.
"""

from __future__ import annotations

from server.modules.custom_factors.client_library import build_client_library_projection


def _stale_item() -> dict:
    return {
        "factor_alias": "Stale|N:1d|$F:1d",
        "factor_ref": "factor:v2:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdead",
        "factor_family_alias": "Stale",
        "factor_family_name": "Stale",
        "owner_username": "alice",
        "owner_ref": "alice",
        "factor_owner_ref": "alice",
        "params": [],
        "parameter_definitions": [],
        "family_formula_fingerprint": "0" * 64,
        "self_formula_fingerprint": "1" * 64,
    }


def test_stale_registration_is_reported_not_raised():
    out = build_client_library_projection(
        {"factors": [_stale_item()], "families": []}, principal="alice",
    )
    assert out["factors"] == []
    assert len(out["unresolved_factors"]) == 1
    entry = out["unresolved_factors"][0]
    assert entry["factor_family_alias"] == "Stale"
    assert entry["factor_alias"].startswith("Stale|")
    assert entry["error"]


def test_clean_payload_reports_nothing_unresolved():
    out = build_client_library_projection({"factors": [], "families": []}, principal="alice")
    assert out["unresolved_factors"] == []
