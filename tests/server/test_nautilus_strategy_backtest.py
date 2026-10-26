from __future__ import annotations

from tests.nautilus_runtime import require_nautilus
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
from server.services.nautilus_bridge.strategy_backtest import run_strategy_replay
from tools.factors.expr import CLOSE


def test_real_nautilus_strategy_run(tmp_path):
    require_nautilus()
    import pytest
    pytest.importorskip("pyarrow")
    item = _real_catalog(tmp_path, count=8)
    result = run_strategy_replay(
        input=item, strategy_kind="threshold",
        factor_bindings={"signal": CLOSE, "confirm": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43, "confirm": "factor:v2:" + "a" * 43},
        product="T", output_dir=tmp_path / "factor-reports",
        max_bars=8,
    )
    assert result["bars"] == 8
    assert result["factor_roles"] == ["confirm", "signal"]
    assert result["publications"] == {"signal": 8, "confirm": 8}
    assert result["factor_plan_nodes"] == 1
    assert result["order_count"] >= 1
    assert (tmp_path / "factor-reports" / "tearsheet.html").is_file()
    assert (tmp_path / "factor-reports" / "orders.csv").is_file()
