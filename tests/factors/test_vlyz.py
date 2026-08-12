from tests.public_factor_source import load_public_factor_module
from tools.data.types import DataFreq


_resolve_bars_or_default = load_public_factor_module(
    "VlYZ"
)._resolve_bars_or_default


def test_yang_zhang_weight_uses_window_day_count():
    assert _resolve_bars_or_default("14d", DataFreq.DAY1, 3) == 14


def test_yang_zhang_weight_falls_back_for_non_daily_window():
    assert _resolve_bars_or_default("bad", DataFreq.DAY1, 3) == 3
    assert _resolve_bars_or_default("2h", DataFreq.HOUR1, 3) == 3
