from __future__ import annotations

from tests.nautilus_runtime import require_nautilus
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
from server.services.nautilus_bridge.strategy_backtest import run_strategy_family_replay
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup, ThresholdState
from tools.factors.expr import CLOSE


def test_real_group_strategy_runs_across_two_products(tmp_path, monkeypatch):
    require_nautilus()
    import pytest
    pytest.importorskip("pyarrow")
    (tmp_path / "T").mkdir()
    (tmp_path / "TL").mkdir()
    inputs = {
        "T": _real_catalog(tmp_path / "T", code="T", month="2403"),
        "TL": _real_catalog(tmp_path / "TL", code="TL", month="2406"),
    }
    from server.services.nautilus_bridge import backtest_runner
    assert not hasattr(backtest_runner, "iter_catalog_bar_batches")
    result = run_strategy_family_replay(
        inputs=inputs, factor_bindings={"signal": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=CrossSectionalGroup(split_count=2, group_index=1),
        output_dir=tmp_path / "group-reports", max_bars=8, batch_minutes=3,
    )
    assert result["products"] == ["T", "TL"]
    assert result["bars"] == 16
    assert result["publications"] == {"signal": 8}
    assert result["batch_count"] >= 2
    assert result["max_batch_bars"] <= 6
    assert result["orders"] >= 1
    assert (tmp_path / "group-reports" / "tearsheet.html").is_file()


def test_real_threshold_family_consumes_signal_and_creates_orders(tmp_path):
    require_nautilus()
    result = run_strategy_family_replay(
        inputs={"T": _real_catalog(tmp_path, count=8)},
        factor_bindings={"signal": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=ThresholdState(entry=1, exit=0),
        output_dir=tmp_path / "threshold-reports", max_bars=8,
    )
    assert result["publications"] == {"signal": 8}
    assert result["orders"] == 1


def test_callback_failure_prevents_report_publication(tmp_path):
    import pytest
    require_nautilus()
    class BrokenThreshold:
        def direction(self, value):
            raise ValueError("injected decision failure")
    with pytest.raises(RuntimeError, match="callback failed") as error:
        run_strategy_family_replay(
            inputs={"T": _real_catalog(tmp_path, count=8)},
            factor_bindings={"signal": CLOSE},
            factor_refs={"signal": "factor:v2:" + "a" * 43},
            family=BrokenThreshold(), output_dir=tmp_path / "invalid-reports", max_bars=8,
        )
    assert "injected decision failure" in str(error.value.__cause__)
    assert not (tmp_path / "invalid-reports").exists()
