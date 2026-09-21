"""Saving a current factor selection must not be blocked by stale metadata."""

from contextlib import nullcontext

import pytest

from server.modules.custom_factors import factor_library_service as service
from server.modules.shared.factor_param_utils import unique_frozen_factor_records
from tools.cli.identities.factor import freeze_factor_identity


def _record(*, alias: str = "Nested|N:10d", params: dict) -> dict:
    return freeze_factor_identity(
        owner_ref="principal:alice",
        family_alias="Nested",
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params=params,
    )


def test_current_row_replaces_stale_same_ref_metadata_on_save(monkeypatch):
    stale = _record(params={"N": "20d"})
    current = _record(params={"N": "10d"})
    unrelated = _record(alias="Nested|N:30d", params={"N": "30d"})
    assert stale["ref"] == current["ref"]
    with pytest.raises(ValueError, match="different frozen records share factor ref"):
        unique_frozen_factor_records([stale, current])

    saved = {}
    monkeypatch.setattr(service, "get_factor_family_instance", lambda *a, **k: object())
    monkeypatch.setattr(service, "_freeze_alias_factor_param_rows", lambda u, f, rows: rows)
    monkeypatch.setattr(service, "_merged_library_metadata", lambda *a, **k: {
        "factor_dependencies": [stale, unrelated],
    })
    monkeypatch.setattr(service, "frozen_factor_records_from_values", lambda rows: [current])
    monkeypatch.setattr(service, "_configuration_factor_resolver", lambda *a, **k: nullcontext())
    monkeypatch.setattr(service, "serialize_factor_param_rows", lambda family, rows: rows)
    monkeypatch.setattr(service, "get_account", lambda user: {"username": user})
    monkeypatch.setattr(service, "build_factor_library_config_factors",
                        lambda *a, **k: [{"ref": "factor:v2:ROW", "alias": "Row"}])
    monkeypatch.setattr(service, "save_factor_param_config",
                        lambda *a, **kw: saved.update(kw) or {"saved": True})

    service.save_current_user_library_config("alice", "Nested", [{"N": "10d"}])

    by_ref = {item["ref"]: item for item in saved["metadata"]["factor_dependencies"]}
    assert by_ref[current["ref"]]["identity"]["params"] == {"N": "10d"}
    assert by_ref[unrelated["ref"]]["identity"]["params"] == {"N": "30d"}
