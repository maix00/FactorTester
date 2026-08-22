from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.modules.single_factor_test import ic
from server.modules.single_factor_test.research_jobs import _execution_payload


def test_ic_execution_payload_preserves_each_factor_family() -> None:
    factors = [
        {
            "factor_family_alias": "MmRateOfChg",
            "alias": "MmRateOfChg|P:CA|N:20d|$F:1d",
        },
        {
            "factor_family_alias": "SgCCS",
            "alias": "SgCCS|N:20d|$F:1d|$Rev",
        },
    ]
    configuration = {
        "configuration_id": "multi-family",
        "revision": 1,
        "fingerprint": "frozen",
        "payload": {
            "shared": {
                "factor_families": [
                    {"alias": "MmRateOfChg"},
                    {"alias": "SgCCS"},
                ],
                "factors": factors,
            },
            "analyses": {"ic": {"product_path_selection_id": "strict-day"}},
        },
    }

    payload = _execution_payload(configuration, "ic")

    assert payload["factors"] == factors
    assert "factor_family_alias" not in payload
    assert "settings" not in payload


def test_ic_run_spec_resolves_factors_across_families(monkeypatch) -> None:
    aliases = [
        "MmRateOfChg|P:CA|N:20d|$F:1d",
        "SgCCS|N:20d|$F:1d|$Rev",
    ]
    factors = {
        alias: SimpleNamespace(alias=alias)
        for alias in aliases
    }
    captured: dict[str, object] = {}
    resolved_owners: list[str] = []

    monkeypatch.setattr(ic, "selection_from_request", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        ic,
        "create_isolated_factor_tester_for_run",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        ic,
        "factor_from_alias",
        lambda alias, **kwargs: (
            resolved_owners.append(kwargs["username"]) or factors[alias]
        ),
    )
    monkeypatch.setattr(
        "server.services.external_factor_artifacts.load_frozen_artifacts",
        lambda _raw: [],
    )

    def capture(_data, _tester, factor_collection, _sink, **_kwargs):
        captured["aliases"] = [factor.alias for factor in factor_collection.factors]
        captured["resolved"] = [
            factor_collection.get_factor_by_alias(alias).alias
            for alias in aliases
        ]

    monkeypatch.setattr(ic, "_run_ic_compute_to_sink", capture)

    payload = {
        "_owner": "18717974771",
        "run_id": "multi-family-ic",
        "product_path_selection_id": "strict-day",
        "factors": [
            {"alias": aliases[0], "factor_owner_ref": "GTHT@owner-a@1"},
            {"alias": aliases[1], "factor_owner_ref": "GTHT@owner-b@2"},
        ],
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
    }

    parsed = ic._parse_ic_params(payload)
    assert parsed[1] == ""
    assert [item["alias"] for item in parsed[2]] == aliases

    ic.execute_ic_run_spec(
        payload,
        sink=object(),
        cancel_event=object(),
    )

    assert captured == {"aliases": aliases, "resolved": aliases}
    assert resolved_owners == ["GTHT@owner-a@1", "GTHT@owner-b@2"]


def test_ic_run_spec_uses_frozen_top_level_window(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(ic, "selection_from_request", lambda *_args, **_kwargs: object())

    def capture_tester(_selection, **kwargs):
        captured["start_dt"] = kwargs["start_dt"]
        captured["end_dt"] = kwargs["end_dt"]
        return object()

    monkeypatch.setattr(ic, "create_isolated_factor_tester_for_run", capture_tester)
    monkeypatch.setattr(ic, "user_obj_for_name", lambda _owner: object())
    monkeypatch.setattr(
        "server.services.external_factor_artifacts.load_frozen_artifacts",
        lambda _raw: [],
    )
    monkeypatch.setattr(ic, "_run_ic_compute_to_sink", lambda *_args, **_kwargs: None)

    ic.execute_ic_run_spec(
        {
            "_owner": "18717974771",
            "run_id": "frozen-window-ic",
            "product_path_selection_id": "strict-day",
            "factors": [],
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "start_time": "00:00",
            "end_time": "23:59",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        },
        sink=object(),
        cancel_event=object(),
    )

    assert str(captured["start_dt"].ts) == "2024-01-01 00:00:00+08:00"
    assert str(captured["end_dt"].ts) == "2024-03-31 23:59:00+08:00"


def test_ic_run_spec_rejects_missing_frozen_window(monkeypatch) -> None:
    monkeypatch.setattr(ic, "selection_from_request", lambda *_args, **_kwargs: object())

    with pytest.raises(ValueError, match="requires start_date and end_date"):
        ic.execute_ic_run_spec(
            {
                "_owner": "18717974771",
                "run_id": "missing-window-ic",
                "product_path_selection_id": "strict-day",
                "factors": [],
            },
            sink=object(),
            cancel_event=object(),
        )


def test_ic_factor_links_use_frozen_execution_identity() -> None:
    alias = "MmRateOfChg|P:CA|N:20d|$F:1d"
    target_ref = (
        "factor:v1:profile-maxa:path:identity:" + "a" * 40 + ":" + "b" * 40
    )
    payload = {
        "factor_refs": {alias: target_ref},
    }

    assert ic._factor_execution_refs(payload) == {
        alias: target_ref,
    }


def test_ic_factor_links_fall_back_to_run_spec_shared_factors() -> None:
    alias = "MmRateOfChg|P:CA|N:20d|$F:1d"
    target_ref = (
        "factor:v1:profile-maxa:path:identity:" + "c" * 40 + ":" + "d" * 40
    )

    assert ic._factor_execution_refs({
        "factor_refs": {},
        "run_spec": {
            "configuration": {
                "shared": {
                    "factors": [{"alias": alias, "factor_ref": target_ref}],
                },
            },
        },
    }) == {alias: target_ref}


def test_ic_factor_links_do_not_reconstruct_from_alias_or_manifest() -> None:
    alias = "MmRateOfChg|P:CA|N:999d|$F:17m|X:arbitrary"
    assert ic._factor_execution_refs({
        "factors": [{"alias": alias}],
        "factor_revision_manifests": [{
            "factor_alias_hash": __import__("hashlib").sha256(
                alias.encode()
            ).hexdigest(),
            "resolved_factor_expr_hash": "a" * 64,
            "resolution_status": "resolved",
        }],
    }) == {}
