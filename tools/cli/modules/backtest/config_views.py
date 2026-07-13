"""Display helpers for backtest draft configuration commands."""

from __future__ import annotations

from typing import Any

from tools.cli.modules.backtest.shared.selectors import selection_label
from tools.cli.table import render_table


GROUP_ADD_HELP_LINES = (
    "group --add 动作说明",
    "  用途: 新增一个或多个分组策略草稿。",
    "  单个新增: group --add --group-name A1 --split-count 5 --group-index 1",
    "  批量新增: group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5",
    "  产品路径: --product-group from-candidates --name 中国期货日盘",
    "  因子: --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'",
)

GROUP_BATCH_HELP_LINES = (
    "group --add --batch 字段说明",
    "  用途: 一次新增一个分组集合中的所有组。",
    "  必填: --group-names NAME...，例如 A1 A2 A3 A4 A5",
    "  分组数: 省略 --split-count 时默认等于 group-names 个数。",
    "  分组序号: 不允许填写 --group-index；按 group-names 顺序自动生成 1..N。",
    "  写法: factortester group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5",
)

STRATEGY_BOOK_HELP_LINES = (
    "backtest strategy-book 命令",
    "  show                         查看当前 strategy/ledger/cash pool 拓扑",
    "  simple                       恢复默认: 每个 strategy 一个私有 ledger/cash pool",
    "  ledger --strategy A1 --ledger shared --cash-pool pool-main [--default]",
    "                               让 strategy A1 可操作 ledger shared，并映射到 cash pool",
    "  cash-pool --cash-pool pool-main --initial-capital-major 100000000 --base-currency CNY",
    "                               设置 cash pool 的初始资金与币种",
)

LEDGER_CONFIG_HELP_LINES = (
    "backtest ledger-config 命令",
    "  show / list",
    "  --ledger LEDGER --fee-mode auto --transaction-fee-source exchange --margin-mode auto --accounting-mode Auto",
    "  --transaction-fee-source 可选: exchange, openctp",
    "  --daily-mark-to-market-enabled true --cost-basis-method fifo",
    "  --cash-reserve-ratio 0.1 --cash-reserve-major 1000000",
    "说明:",
    "  这些字段属于 ledger-owned 配置，会传给后端 LedgerConfig；不是普通 per-strategy 字段。",
    "  其他字段可用 --field value 或 field=value 透传，但后端会按 LedgerConfig 校验/忽略未知 metadata。",
)


def group_list_lines(groups: list[dict[str, Any]]) -> list[str]:
    if not groups:
        return ["  （空）"]
    lines: list[str] = []
    for index, group_item in enumerate(groups, start=1):
        name = group_item.get("name") or group_item.get("id") or f"group-{index}"
        parts = [str(name)]
        split_count = group_item.get("split_count", group_item.get("splitCount"))
        group_index = group_item.get("group_index", group_item.get("groupIndex"))
        factor = group_item.get("factor", group_item.get("factorAlias"))
        if split_count is not None:
            parts.append(f"分组数={split_count}")
        if group_index is not None:
            parts.append(f"分组序号={group_index}")
        product_path = selection_label(group_item.get("product_path_selection"))
        if product_path:
            parts.append(f"产品路径={product_path}")
        if factor:
            parts.append(f"因子={factor}")
        lines.append(f"  {index}. " + " · ".join(parts))
    return lines


def long_short_list_lines(configs: list[dict[str, Any]]) -> list[str]:
    if not configs:
        return ["  （空）"]
    lines: list[str] = []
    for index, config in enumerate(configs, start=1):
        long_group = config.get("long_group") or {}
        short_group = config.get("short_group") or {}
        long_label = long_group.get("name") or long_group.get("id") or config.get("long_group_id") or config.get("longGroupId")
        short_label = short_group.get("name") or short_group.get("id") or config.get("short_group_id") or config.get("shortGroupId")
        lines.append(
            f"  {index}. {config.get('name') or f'ls-{index}'} · "
            f"多头={long_label} · "
            f"空头={short_label}"
        )
    return lines


def strategy_book_lines(payload: dict[str, Any]) -> list[str]:
    strategies = payload.get("strategies") or {}
    cash_pools = payload.get("cash_pools") or {}
    cash_pool_configs = payload.get("cash_pool_configs") or {}
    lines = ["StrategyBook"]
    if not strategies:
        lines.append("  模式: StrategyBookSimple · 每个 strategy 一个私有 ledger / cash pool")
    else:
        rows = []
        for strategy, entry in strategies.items():
            entry_map = entry if isinstance(entry, dict) else {"ledger_ids": [entry], "default_ledger_id": entry}
            ledger_ids = list(entry_map.get("ledger_ids") or entry_map.get("ledgers") or [])
            default = str(entry_map.get("default_ledger_id") or (ledger_ids[0] if ledger_ids else ""))
            pools = ", ".join(f"{ledger}->{cash_pools.get(ledger, ledger)}" for ledger in ledger_ids)
            rows.append((strategy, ", ".join(ledger_ids), default, pools))
        lines.extend(render_table(("strategy", "ledgers", "default", "cash pools"), rows, indent="  ", max_widths=(20, 28, 18, 42)))
    if cash_pool_configs:
        lines.append("Cash pools")
        rows = [
            (
                pool_id,
                config.get("initial_capital_major", ""),
                config.get("base_currency", ""),
                config.get("currency_conversion_fee_rate", ""),
            )
            for pool_id, config in cash_pool_configs.items()
            if isinstance(config, dict)
        ]
        lines.extend(render_table(("cash_pool", "initial", "currency", "fx_fee"), rows, indent="  ", max_widths=(24, 14, 10, 10)))
    return lines


def ledger_config_lines(configs: dict[str, Any]) -> list[str]:
    if not configs:
        return ["  （空；使用后端注册字段的默认/推断规则）"]
    rows = []
    for ledger, config in configs.items():
        config_map = config if isinstance(config, dict) else {}
        summary = ", ".join(f"{key}={value}" for key, value in sorted(config_map.items()))
        rows.append((ledger, summary))
    return list(render_table(("ledger", "config"), rows, indent="  ", max_widths=(24, 90)))


def group_detail_lines(group: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if group.get("name"):
        lines.append(f"名称: {group['name']}")
    split_count = group.get("split_count", group.get("splitCount"))
    group_index = group.get("group_index", group.get("groupIndex"))
    factor = group.get("factor", group.get("factorAlias"))
    if split_count is not None:
        lines.append(f"分组数: {split_count}")
    if group_index is not None:
        lines.append(f"分组序号: {group_index}")
    lines.append(f"产品路径: {selection_label(group.get('product_path_selection'))}")
    lines.append(f"因子: {factor}")
    return lines
