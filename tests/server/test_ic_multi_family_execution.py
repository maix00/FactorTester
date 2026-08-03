from __future__ import annotations

from types import SimpleNamespace

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

    monkeypatch.setattr(ic, "selection_from_request", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        ic,
        "create_isolated_factor_tester_for_run",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        ic,
        "factor_from_alias",
        lambda alias, **_kwargs: factors[alias],
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
        "factors": [{"alias": alias} for alias in aliases],
        "settings": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
        },
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
