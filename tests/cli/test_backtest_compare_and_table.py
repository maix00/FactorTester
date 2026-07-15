from __future__ import annotations

from tools.cli.modules.backtest.compare_commands import handle_compare_command
from tools.cli.table import display_width, truncate_display


def test_truncate_display_handles_rich_in_place_truncate() -> None:
    value = truncate_display("模式: " + "很长" * 80, 24)

    assert isinstance(value, str)
    assert display_width(value) <= 24


def test_compare_help_token_after_preset_does_not_run_backtest(capsys) -> None:
    called = False

    def run_backtest(*args, **kwargs) -> None:
        nonlocal called
        called = True

    handle_compare_command(
        object(),
        ("factor-grid", "--help"),
        volume_rate=0.02,
        factor_family="SgCCS",
        n_values=(),
        f_values=(),
        product_groups=(),
        rev=True,
        top=12,
        liquidity_mode="inherit",
        participation_rate=None,
        verbose=False,
        run_backtest=run_backtest,
    )

    assert not called
    assert "factor-grid" in capsys.readouterr().out
