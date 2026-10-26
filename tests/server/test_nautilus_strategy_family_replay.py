from __future__ import annotations

from tests.nautilus_runtime import require_nautilus
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog
from server.services.nautilus_bridge.strategy_backtest import run_strategy_family_replay
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup
from tools.factors.expr import CLOSE


def test_real_group_strategy_runs_across_two_products(tmp_path):
    require_nautilus()
    import pytest
    pytest.importorskip("pyarrow")
    (tmp_path / "T").mkdir()
    (tmp_path / "TL").mkdir()
    inputs = {
        "T": _real_catalog(tmp_path / "T", code="T", month="2403"),
        "TL": _real_catalog(tmp_path / "TL", code="TL", month="2406"),
    }
    result = run_strategy_family_replay(
        inputs=inputs, factor_bindings={"signal": CLOSE},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=CrossSectionalGroup(split_count=2, group_index=1),
        output_dir=tmp_path / "group-reports", max_bars=8,
    )
    assert result["products"] == ["T", "TL"]
    assert result["publications"] == {"signal": 8}
    assert result["orders"] >= 1
    assert (tmp_path / "group-reports" / "tearsheet.html").is_file()
