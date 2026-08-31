from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.cli.release.research_reporting.references import factor_identity


def test_factor_identity_batch_uses_one_external_process(monkeypatch) -> None:
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        requests = json.loads(kwargs["input"])["requests"]
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({
                "schema_version": 1,
                "results": [{
                    "index": index,
                    "identity": request["identity"],
                        "canonical_identity": request["identity"],
                        "family_formula_fingerprint": "a" * 64,
                        "self_formula_fingerprint": "b" * 64,
                        "valid": True,
                } for index, request in enumerate(requests)],
            }),
        )

    monkeypatch.setattr(
        factor_identity,
        "_validator_process",
        lambda: (["factor-alias-validator"], None, {}),
    )
    monkeypatch.setattr(factor_identity.subprocess, "run", run)
    requests = [{
        "source_file": f"/factors/Momentum{window}.py",
        "identity": f"Momentum|N:{window}d",
        "object_kind": "factor",
        "blob_hash": str(window) * 40,
    } for window in range(1, 5)]

    values = factor_identity.validate_canonical_factor_identities(requests)

    assert values == [request["identity"] for request in requests]
    assert len(calls) == 1
    assert len(json.loads(calls[0][1]["input"])["requests"]) == 4


def test_packaged_client_reports_missing_engine_helper(monkeypatch) -> None:
    monkeypatch.delenv(
        "FACTORTESTER_FACTOR_ALIAS_VALIDATOR", raising=False,
    )
    monkeypatch.setattr(factor_identity, "__file__", str(
        Path("/Applications/FTClient.app/Contents/Resources/")
        / "tools/cli/release/research_reporting/references/factor_identity.py"
    ))

    try:
        factor_identity._validator_process()
    except ValueError as error:
        assert "FactorTester engine helper" in str(error)
    else:
        raise AssertionError("missing engine helper was not rejected")
