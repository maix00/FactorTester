from __future__ import annotations

import pandas as pd
import pytest

from tools.backtest_engines.market_rules import (
    MissingMarketRule,
    RuleFallbackPolicy,
    RuleProvenance,
    TemporalRuleProvider,
)


def test_market_rule_provider_marks_latest_fallback_as_approximation() -> None:
    provider = TemporalRuleProvider(
        {"A": [(pd.Timestamp("2025-01-01"), 0.10)]},
        latest={"B": 0.20},
        default=0.30,
    )

    historical = provider.resolve(
        "A", pd.Timestamp("2026-01-01"), RuleFallbackPolicy.STRICT_HISTORICAL
    )
    latest = provider.resolve(
        "B", pd.Timestamp("2024-01-01"), RuleFallbackPolicy.LATEST_AVAILABLE
    )
    default = provider.resolve(
        "C", pd.Timestamp("2024-01-01"), RuleFallbackPolicy.CONFIGURED_DEFAULT
    )

    assert historical.provenance == RuleProvenance.EFFECTIVE_AT
    assert not historical.approximated
    assert latest.provenance == RuleProvenance.AS_OF_LATEST
    assert latest.approximated
    assert default.provenance == RuleProvenance.CONFIGURED_DEFAULT

    with pytest.raises(MissingMarketRule):
        provider.resolve(
            "B", pd.Timestamp("2024-01-01"), RuleFallbackPolicy.STRICT_HISTORICAL
        )
