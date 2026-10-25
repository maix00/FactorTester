from datetime import date

import pytest

from server.services.nautilus_bridge.position_offsets import effective_execution_offset


def test_deferred_close_today_ages_only_when_exchange_trading_day_changes():
    # The wall-clock date can cross midnight while the exchange session keeps
    # the same trading-day identity.
    assert effective_execution_offset(
        "close_today", signal_trading_day=date(2025, 1, 3),
        execution_trading_day=date(2025, 1, 3),
    ) == "close_today"

    # A deferred order becomes close-yesterday at the next exchange trading day.
    assert effective_execution_offset(
        "close_today", signal_trading_day=date(2025, 1, 3),
        execution_trading_day=date(2025, 1, 6),
    ) == "close_yesterday"


@pytest.mark.parametrize("offset", ["open", "close", "close_yesterday"])
def test_other_offsets_do_not_change_at_trading_day_boundary(offset: str):
    assert effective_execution_offset(
        offset, signal_trading_day=date(2025, 1, 3),
        execution_trading_day=date(2025, 1, 6),
    ) == offset


def test_offset_resolution_rejects_unknown_or_backwards_day():
    with pytest.raises(ValueError, match="unknown position offset"):
        effective_execution_offset(
            "close_now", signal_trading_day=date(2025, 1, 3),
            execution_trading_day=date(2025, 1, 6),
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot precede"):
        effective_execution_offset(
            "close_today", signal_trading_day=date(2025, 1, 6),
            execution_trading_day=date(2025, 1, 3),
        )


def test_offset_resolution_requires_pre_resolved_exchange_day_values():
    with pytest.raises(TypeError, match="resolved date values"):
        effective_execution_offset(
            "close_today", signal_trading_day=date(2025, 1, 3),
            execution_trading_day="2025-01-06",  # type: ignore[arg-type]
        )
