"""Backtest results view text helpers."""

from __future__ import annotations


RESULTS_HELP_LINES = (
    "backtest results 命令",
    "  summary                         最近一次运行的统计表格",
    "  equity                          最近一次运行的多策略净值图",
    "  attribution [--group-name NAME]  归因摘要: gross / fee / net / final",
    "    --by product|ledger|cash-pool 按产品/账本/资金池聚合手续费",
    "    --top N                       聚合表显示前 N 行(默认10)",
    "  ledgers [--group-name NAME]      按 ledger/cash pool 汇总成交落账回放",
    "  detail --group-name NAME         查看 web 组内 overlay 的贡献/费率摘要",
    "    --level product|contract      产品或合约层级(默认product)",
    "  ranking                          查看分组排序能力摘要",
    "  snapshot --index N              查看第 N 个时间点的持仓/资金快照",
    "  snapshot --timestamp-ms MS      查看指定 epoch 毫秒附近的快照",
    "  order-flow [--group-name NAME]  查看订单流明细(时间/品种/数量/成交价/状态)",
    "    --show fee                    显示 fee_cost / cash / margin 诊断列",
    "    --ledger ID                   只显示指定账本的记录",
    "    --cash-pool ID                只显示指定资金池的记录",
    "    --order-id ID                 只看某笔订单的完整生命周期",
    "    --limit N                     每个策略最多显示的记录数(默认20, 0=全部)",
    "    --counts-only                 只显示记录条数，不展开明细",
    "",
    "输出选项（所有 results 子命令通用）:",
    "  --output PATH                   写入文件",
    "  --no-terminal                   不打印到终端，仅写文件",
    "  --append                        追加写入文件而不是覆盖",
)


def results_help_lines() -> tuple[str, ...]:
    return RESULTS_HELP_LINES
