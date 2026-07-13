"""Display helpers for backtest compare commands."""

from __future__ import annotations

from typing import Any

from tools.cli.modules.backtest import results_data as results_data_formatter
from tools.cli.table import render_table


COMPARE_HELP_LINES = (
    "backtest compare 命令",
    "  volume-capacity-margin [--volume-rate 0.02]",
    "    在一次后端 run 中复制当前草稿为三套场景:",
    "      1. 成交量容量=无限 / 保证金=关闭",
    "      2. 成交量容量=成交量参与率 / 保证金=关闭",
    "      3. 成交量容量=无限 / 保证金=auto",
    "  factor-grid --factor-family NAME [--n 1m --n 2m] [--f 1m] [--product-group 中国期货日盘]",
    "    继承当前草稿和已注册 policy/local-settings，批量替换因子参数和可选产品组。",
    "    可加 --volume-capacity-mode infinite|volume_participation 覆盖模板内成交量容量设置。",
    "",
    "示例:",
    "  factortester backtest compare volume-capacity-margin --volume-rate 0.02",
    "  factortester backtest compare factor-grid --factor-family SgCCS --product-group 中国期货夜盘 --product-group 中国期货日盘 --n 2m --f 1m --volume-capacity-mode infinite",
)


def compare_result_summary_lines(data: dict[str, Any], scenarios: list[dict[str, str]]) -> list[str]:
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    scenario_labels = [scenario["label"] for scenario in scenarios]
    rows = []
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        scenario_label = next((label for label in scenario_labels if name.startswith(f"{label} · ")), "")
        if not scenario_label:
            continue
        base_name = name[len(scenario_label) + 3:]
        curve = results_data_formatter.group_equity_curve(group)
        initial = curve[0] if curve else 0.0
        final = curve[-1] if curve else 0.0
        rows.append((
            scenario_label,
            base_name,
            f"{final:,.2f}" if curve else "",
            results_data_formatter.pct(final / initial - 1.0) if initial else "",
            len(curve),
        ))
    if not rows:
        return []
    lines = ["", "批量对比摘要"]
    lines.extend(render_table(
        ("场景", "策略", "最终权益", "收益率", "点数"),
        rows,
        indent="  ",
        aligns=("left", "left", "right", "right", "right"),
        max_widths=(22, 24, 16, 10, 8),
    ))
    return lines


def factor_grid_result_summary_lines(data: dict[str, Any], scenarios: list[dict[str, str]], *, top: int) -> list[str]:
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    scenario_by_key = {scenario["key"]: scenario for scenario in scenarios}
    rows: list[tuple[float, str, str, float, int]] = []
    for group in groups:
        scenario_key = str(group.get("compare_scenario") or "")
        scenario = scenario_by_key.get(scenario_key)
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        if scenario is None:
            scenario = next((item for item in scenarios if name.startswith(f"{item['label']} · ")), None)
        if scenario is None:
            continue
        prefix = f"{scenario['label']} · "
        strategy_name = name[len(prefix):] if name.startswith(prefix) else name
        curve = results_data_formatter.group_equity_curve(group)
        if not curve:
            continue
        initial = curve[0]
        final = curve[-1]
        ret = final / initial - 1.0 if initial else 0.0
        rows.append((ret, scenario["label"], strategy_name, final, len(curve)))
    rows.sort(key=lambda item: item[0], reverse=True)
    if top > 0:
        rows = rows[:top]
    if not rows:
        return []
    lines = ["", "因子参数/产品组收益率排行"]
    lines.extend(render_table(
        ("排名", "收益率", "最终权益", "策略", "候选", "点数"),
        [
            (index, results_data_formatter.pct(ret), f"{final:,.2f}", strategy, scenario_label, points)
            for index, (ret, scenario_label, strategy, final, points) in enumerate(rows, start=1)
        ],
        indent="  ",
        aligns=("right", "right", "right", "left", "left", "right"),
        max_widths=(6, 10, 16, 24, 48, 8),
    ))
    return lines
