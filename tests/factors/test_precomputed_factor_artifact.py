from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.factors.PrecomputedFactorArtifact import PrecomputedFactorArtifact


@dataclass(frozen=True)
class _Product:
    name: str


def _write_artifact(
    tmp_path: Path,
    *,
    table: pd.DataFrame | None = None,
    factor_hash: str | None = None,
    timing: dict | None = None,
) -> tuple[Path, dict[str, _Product]]:
    products = {"A.DCE": _Product("A.DCE"), "RB.SHF": _Product("RB.SHF")}
    signals = table if table is not None else pd.DataFrame(
        [[1.0, np.nan], [2.0, -1.0]],
        index=pd.DatetimeIndex(["2026-01-02", "2026-01-05"], name="date"),
        columns=["A.DCE", "RB.SHF"],
    )
    factor_path = tmp_path / "factor.parquet"
    signals.to_parquet(factor_path)
    digest = hashlib.sha256(factor_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "status": "ready_for_gtht_import_contract",
        "alpha_id": "external_momentum",
        "factor": {
            "path": str(factor_path),
            "sha256": factor_hash or digest,
            "layout": "date_by_product_wide",
        },
        "universe": {},
        "timing": timing or {
            "information_time": "daily_bar_close",
            "execution": "next_bar",
            "same_close_execution_forbidden": True,
        },
        "research": {"status": "experimental_unvalidated"},
        "gtht": {"factor_mode": "precomputed", "import_contract_available": False},
    }
    manifest_path = tmp_path / "gtht_handoff.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, products


def test_loads_valid_artifact_and_constructs_factor_run_result(tmp_path: Path) -> None:
    manifest, products = _write_artifact(tmp_path)
    artifact = PrecomputedFactorArtifact.load(manifest, product_resolver=products)

    assert artifact.alpha_id == "external_momentum"
    assert list(artifact.signals.columns) == [products["A.DCE"], products["RB.SHF"]]
    assert artifact.supports_vectorized()
    assert not artifact.supports_incremental()
    result = artifact.to_run_result()
    pd.testing.assert_frame_equal(result.table, artifact.signals)
    pd.testing.assert_frame_equal(result.data_present_mask, artifact.signals.notna())
    assert result.provenance["factor_sha256"]
    assert result.provenance["execution"] == "next_bar"
    assert artifact._structural_key() == artifact.backtest_factor_cache_key()


def test_frozen_descriptor_reloads_executable_factor(tmp_path: Path, monkeypatch) -> None:
    from server.services import external_factor_artifacts

    manifest, products = _write_artifact(tmp_path)
    monkeypatch.setattr(
        external_factor_artifacts,
        "_resolve_cn_futures",
        products.get,
    )
    frozen = external_factor_artifacts.validate_and_freeze(str(manifest))

    factor = external_factor_artifacts.factor_by_alias(
        [frozen], "external_momentum",
    )

    assert factor is not None
    assert factor.alias == "external_momentum"
    assert external_factor_artifacts.result_metadata([frozen]) == [{
        "artifact_id": frozen["artifact_id"],
        "alpha_id": "external_momentum",
        "manifest_sha256": frozen["manifest_sha256"],
        "factor_sha256": frozen["factor_sha256"],
    }]


def test_frozen_descriptor_loads_artifact_once(tmp_path: Path, monkeypatch) -> None:
    from server.services import external_factor_artifacts

    manifest, products = _write_artifact(tmp_path)
    monkeypatch.setattr(
        external_factor_artifacts,
        "_resolve_cn_futures",
        products.get,
    )
    frozen = external_factor_artifacts.validate_and_freeze(str(manifest))
    real_load = PrecomputedFactorArtifact.load
    calls = []

    def counted_load(*args, **kwargs):
        calls.append(args[0])
        return real_load(*args, **kwargs)

    monkeypatch.setattr(PrecomputedFactorArtifact, "load", counted_load)

    loaded = external_factor_artifacts.load_frozen_artifacts([frozen])

    assert [factor.alias for factor in loaded] == ["external_momentum"]
    assert [str(path) for path in calls] == [frozen["manifest_path"]]


def test_frozen_descriptor_rejects_post_submission_change(
    tmp_path: Path, monkeypatch,
) -> None:
    from server.services import external_factor_artifacts

    manifest, products = _write_artifact(tmp_path)
    monkeypatch.setattr(
        external_factor_artifacts,
        "_resolve_cn_futures",
        products.get,
    )
    frozen = external_factor_artifacts.validate_and_freeze(str(manifest))
    frozen["factor_sha256"] = "changed"

    with pytest.raises(ValueError, match="changed after submission"):
        external_factor_artifacts.load_frozen_artifacts([frozen])


def test_factor_tester_calculates_factor_like_artifact_into_run_result(
    tmp_path: Path,
) -> None:
    from tools.factors.FactorTester import FactorTester, _active_tester

    manifest, products = _write_artifact(tmp_path)
    artifact = PrecomputedFactorArtifact.load(
        manifest, product_resolver=products,
    )
    tester = FactorTester(products=list(products.values()), alias="external-test")
    token = _active_tester.set(tester)
    try:
        tester.calc_factor(artifact, parallel=False)
    finally:
        _active_tester.reset(token)

    result = tester.results[artifact]
    pd.testing.assert_frame_equal(result.table, artifact.signals)
    assert result.provenance["factor_sha256"] == artifact.provenance["factor_sha256"]


def test_aligns_trading_days_to_actual_market_signal_times(tmp_path: Path) -> None:
    manifest, products = _write_artifact(tmp_path)
    artifact = PrecomputedFactorArtifact.load(manifest, product_resolver=products)
    index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(["2026-01-02", "2026-01-05"]),
            pd.to_datetime(["2026-01-02 15:00", "2026-01-05 15:00"]),
        ],
        names=["trading_day", "trade_time"],
    )
    schedule = pd.DataFrame({"market": [1.0, 2.0]}, index=index)

    aligned = artifact.align_to_market_schedule(schedule)

    assert aligned.index.equals(index)
    assert aligned.loc[(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-02 15:00")), products["A.DCE"]] == 1.0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"factor_hash": "0" * 64}, "hash mismatch"),
        ({
            "timing": {
                "information_time": "daily_bar_close",
                "execution": "same_bar",
                "same_close_execution_forbidden": False,
            }
        }, "next_bar"),
    ],
)
def test_rejects_invalid_provenance(tmp_path: Path, change: dict, message: str) -> None:
    manifest, products = _write_artifact(tmp_path, **change)
    with pytest.raises(ValueError, match=message):
        PrecomputedFactorArtifact.load(manifest, product_resolver=products)


def test_rejects_unknown_or_duplicate_product_mapping(tmp_path: Path) -> None:
    manifest, products = _write_artifact(tmp_path)
    with pytest.raises(ValueError, match="unknown GTHT products"):
        PrecomputedFactorArtifact.load(
            manifest, product_resolver={"A.DCE": products["A.DCE"]}
        )
    same = _Product("same")
    with pytest.raises(ValueError, match="same GTHT product"):
        PrecomputedFactorArtifact.load(
            manifest, product_resolver={"A.DCE": same, "RB.SHF": same}
        )


def test_rejects_infinity_and_non_normalized_daily_index(tmp_path: Path) -> None:
    infinite = pd.DataFrame(
        [[np.inf]], index=pd.DatetimeIndex(["2026-01-02"]), columns=["A.DCE"]
    )
    manifest, products = _write_artifact(tmp_path, table=infinite)
    with pytest.raises(ValueError, match="infinity"):
        PrecomputedFactorArtifact.load(manifest, product_resolver=products)

    intraday = pd.DataFrame(
        [[1.0]], index=pd.DatetimeIndex(["2026-01-02 15:00"]), columns=["A.DCE"]
    )
    manifest, products = _write_artifact(tmp_path, table=intraday)
    with pytest.raises(ValueError, match="normalized to midnight"):
        PrecomputedFactorArtifact.load(manifest, product_resolver=products)
