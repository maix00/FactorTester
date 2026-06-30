"""MarketRuleModule — declares market-rule fallback controls."""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class MarketRuleModule(ExecutableModule):
    key: ClassVar[str] = "market_rules"
    label: ClassVar[str] = "市场规则"

    market_rule_fallback: ClassVar[FieldRef[str]] = FieldRef("market_rule_fallback")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "market_rule_fallback": FieldDefinition(
            public=True,
            default="latest_available",
            control_template="select",
            tab="market_rules",
            options=(
                ("latest_available", "使用最新规则并标记近似"),
                ("strict_historical", "缺失即报错"),
                ("configured_default", "使用注册默认值并标记近似"),
            ),
            chip_template="规则回退: {value}",
            tab_label="市场规则",
            tab_order=170,
        ),
    }
