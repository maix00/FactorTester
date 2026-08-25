from __future__ import annotations

import json
from pathlib import Path

from tools.factors.alias_validator import (
    _load_factor_family,
    canonicalize_factor_aliases,
    describe_factor_family,
    instantiate_factor_family,
    main,
)


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "QuickAliasFamily.py"
    path.write_text(
        "\n".join([
            "from tools.factors import FactorFamily",
            "from tools.parameters import DataColumnParam, WindowParam",
            "class QuickAliasFamily(FactorFamily):",
            "    @staticmethod",
            "    def factor_expr():",
            "        P = DataColumnParam('P', default_value='CA')",
            "        N = WindowParam('N', default_value='10d')",
            "        return P - P.shift(N)",
        ]),
        encoding="utf-8",
    )
    return path


def test_batch_alias_validation_loads_one_family_once(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _load_factor_family.cache_clear()
    requests = [{
        "source_file": str(source),
        "blob_hash": "a" * 40,
        "identity": f"QuickAliasFamily|P:CA|N:{window}|$F:30m",
        "object_kind": "factor",
    } for window in ("5d", "10d", "20d", "60d")]

    results = canonicalize_factor_aliases(requests)

    assert all(item["valid"] for item in results)
    assert _load_factor_family.cache_info().misses == 1


def test_batch_alias_validation_reports_legacy_display_alias(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)

    results = canonicalize_factor_aliases([{
        "source_file": str(source),
        "blob_hash": "b" * 40,
        "identity": "QuickAliasFamily|P:[CA]|N:20d",
        "object_kind": "factor",
    }])

    assert results[0]["index"] == 0
    assert results[0]["identity"] == "QuickAliasFamily|P:[CA]|N:20d"
    assert results[0]["canonical_identity"] == (
        "QuickAliasFamily|P:CA|N:20d|$F:30m"
    )
    assert results[0]["valid"] is False
    assert results[0]["family_formula_fingerprint"]
    assert results[0]["self_formula_fingerprint"]


def test_standalone_alias_validator_reads_one_json_batch(
    tmp_path: Path, capsys,
) -> None:
    source = _source(tmp_path)
    request_file = tmp_path / "aliases.json"
    request_file.write_text(json.dumps({"requests": [{
        "source_file": str(source),
        "blob_hash": "c" * 40,
        "identity": "QuickAliasFamily|P:CA|N:20d|$F:30m",
        "object_kind": "factor",
    }]}), encoding="utf-8")

    exit_code = main(["--input", str(request_file)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["results"][0]["canonical_identity"] == (
        "QuickAliasFamily|P:CA|N:20d|$F:30m"
    )


def test_factor_engine_helper_describes_and_instantiates_family(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    request = {
        "source_file": str(source),
        "blob_hash": "d" * 40,
        "family": "QuickAliasFamily",
    }

    description = describe_factor_family(request)
    candidate = instantiate_factor_family({
        **request,
        "params": {"P": "CA", "N": "20d", "$F": "1d"},
    })

    assert {item["alias"] for item in description["params"]} >= {
        "P", "N", "$F", "$Rev",
    }
    assert candidate["alias"] == "QuickAliasFamily|P:CA|N:20d|$F:1d"
    assert candidate["params"]["N"] == "20d"
