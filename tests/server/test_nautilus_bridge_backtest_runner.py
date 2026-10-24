"""Isolated real T/TL catalog replay; never creates a production Job."""

from __future__ import annotations

from decimal import Decimal
from itertools import islice
from pathlib import Path

import pytest

from server.services.nautilus_bridge.backtest_runner import (
    ReplayInput, run_small_catalog_replay,
)
from server.services.nautilus_bridge.catalog import stage_contract_minute_catalog
from server.services.nautilus_bridge.market_data import FuturesContractSpec, iter_minute_bars
from tests.nautilus_runtime import require_nautilus
from tests.nautilus_source_fixture import resolved_contract_minute_source


ROOT = Path("/Users/maxdeux/Documents/GTHT/data/sources/LocalCNFutures")


def _real_catalog(tmp_path, code="T", month="2403", count=8):
    source = ROOT / f"data_mink_product/CFFEX_F_{code}_{month}.parquet"
    if not source.is_file():
        pytest.skip("read-only local T/TL source unavailable")
    original = list(islice(iter_minute_bars(source, batch_size=4), count))
    assert len(original) == count
    spec = FuturesContractSpec(
        instrument_code=f"{code}{month}", venue="CFFEX", underlying=code,
        price_increment=Decimal("0.005" if code == "T" else "0.01"),
        price_precision=3 if code == "T" else 2,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic replay probe metadata, not exchange authority",
        resolved_source=resolved_contract_minute_source(),
    )
    catalog = tmp_path / "catalog"
    receipt = stage_contract_minute_catalog(
        source, catalog, contract_uid=f"CFFEX|F|{code}|{month}",
        instrument_spec=spec,
        start_ns=original[0].clock.interval_end_ns,
        end_ns=original[-1].clock.interval_end_ns,
        batch_bars=3, max_bars=count,
    )
    return ReplayInput(catalog, receipt.contract_uid)


@pytest.mark.parametrize("code,month", [("T", "2403"), ("TL", "2406")])
def test_real_small_window_market_replay_and_native_reports(tmp_path, code, month):
    require_nautilus()
    pytest.importorskip("pyarrow")
    item = _real_catalog(tmp_path, code, month)
    out = tmp_path / "reports"
    result = run_small_catalog_replay((item,), out, max_input_bars=8, batch_minutes=3)
    assert result.input_bars == 8
    assert result.batch_count >= 2
    assert result.max_batch_bars <= 3
    assert result.native_iterations == 8
    assert result.native_orders == 0
    assert result.factor_claim.startswith("none")
    assert (out / "tearsheet.html").stat().st_size > 100
    assert (out / "account.csv").is_file()


def test_synthetic_order_probe_is_labeled_and_never_claims_factor_result(tmp_path):
    require_nautilus()
    pytest.importorskip("pyarrow")
    item = _real_catalog(tmp_path)
    result = run_small_catalog_replay(
        (item,), tmp_path / "reports", max_input_bars=8,
        batch_minutes=3, synthetic_order_probe=True)
    assert result.mode == "synthetic_order_probe"
    assert result.native_orders >= 1
    assert result.factor_claim.startswith("none")
    assert result.next_bar_open_orders == 2
    assert result.max_batch_events == result.max_batch_bars
    assert len(result.probe_fill_prices) == result.native_orders
    assert "native open leg" in result.execution_assumptions[1]
    assert "liquidity_consumption" in result.execution_assumptions[2]
    assert "not a configurable whole-Bar participation-rate cap" in result.execution_assumptions[4]


def test_t_and_tl_share_one_native_replay_clock_without_second_panel(tmp_path):
    require_nautilus()
    pytest.importorskip("pyarrow")
    (tmp_path / "t").mkdir()
    (tmp_path / "tl").mkdir()
    t = _real_catalog(tmp_path / "t", "T", "2403")
    tl = _real_catalog(tmp_path / "tl", "TL", "2406")
    result = run_small_catalog_replay(
        (t, tl), tmp_path / "reports", max_input_bars=16, batch_minutes=3,
        position_cost_basis="WEIGHTED_AVERAGE",
        position_cost_basis_by_instrument={
            "T2403.CFFEX": "FIFO",
            "TL2406.CFFEX": "HIFO",
        })
    assert result.input_bars == result.native_iterations == 16
    assert len(result.instrument_ids) == 2
    assert result.max_batch_bars <= 6
    assert result.native_orders == 0
    assert result.position_cost_basis == "WEIGHTED_AVERAGE"
    assert result.position_cost_basis_by_instrument == {
        "T2403.CFFEX": "FIFO", "TL2406.CFFEX": "HIFO",
    }


def test_frozen_ref_without_resolved_expression_is_not_misrepresented(tmp_path):
    with pytest.raises(NotImplementedError, match="ref alone"):
        run_small_catalog_replay(
            (ReplayInput(tmp_path / "missing", "CFFEX|F|T|2403"),),
            tmp_path / "out", frozen_factor_ref="factor:v2:example")
