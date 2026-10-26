"""TradeResearch-owned public strategy families.

A strategy family is a reusable public rule template.  A strategy binds a
family to frozen parameters, factor-role bindings and a product scope.  The
Nautilus bridge is an execution adapter only; it must consume a frozen
strategy plan and must not define or interpret the family catalog itself.
"""

from __future__ import annotations

PUBLIC_STRATEGY_FAMILIES = (
    {
        "family_id": "threshold",
        "name": "因子阈值策略家族",
        "description": "按因子阈值进入/退出，支持 long_short、long_only、short_only。",
        "parameters": ("entry_threshold", "exit_threshold", "side_mode"),
    },
    {
        "family_id": "cross_sectional_group",
        "name": "因子分组第N组策略家族",
        "description": "按因子横截面排序分组，交易指定第 N 组。",
        "parameters": ("split_count", "group_index"),
    },
)


def list_public_strategy_families() -> list[dict]:
    return [dict(item, parameters=list(item["parameters"]))
            for item in PUBLIC_STRATEGY_FAMILIES]


def strategy_family(family_id: str) -> dict | None:
    return next((dict(item, parameters=list(item["parameters"]))
                 for item in PUBLIC_STRATEGY_FAMILIES
                 if item["family_id"] == family_id), None)
