"""Deterministic bounded tables for retained research result summaries."""


def metric_rows(row):
    summary = row.get("result_summary") or {}
    if row["kind"] == "ic":
        stats = summary.get("ic_stats") or {}
        columns = list(stats.get("columns") or [])
        return [
            (
                f"{metric_alias(item.get('index'))} · {column}",
                display(item.get(column)),
            )
            for item in stats.get("rows") or []
            if isinstance(item, dict)
            for column in columns[1:9]
            if column in item
        ][:64] or scalar_metrics(summary)
    if row["kind"] == "backtest":
        metrics = summary.get("metrics") or {}
        result = [
            (f"{group_alias(group)} · {metric_alias(name)}", display(value))
            for group, values in sorted(metrics.items())
            if isinstance(values, dict)
            for name, value in sorted(values.items())
            if name.lower().replace("_", " ") in {
                "sharpe", "sharpe ratio", "annual return",
                "annualized return", "max drawdown", "total return",
            }
        ]
        for group in summary.get("groups") or []:
            if not isinstance(group, dict):
                continue
            for name in ("annualized_return", "total_return", "max_drawdown"):
                if name in group:
                    result.append((
                        f"{group_alias(group.get('key'))} · {metric_alias(name)}",
                        display(group[name]),
                    ))
        return result[:64] or scalar_metrics(summary)
    return scalar_metrics(summary)


def scalar_metrics(summary):
    return [
        (metric_alias(key), display(value))
        for key, value in sorted(summary.items())
        if isinstance(value, (str, int, float, bool))
        and key not in {"full_result_bytes", "pid"}
    ][:32] or [("结果摘要", "无有界统计指标")]


def display(value):
    return f"{value:.6g}" if isinstance(value, float) else str(value)[:80]


def metric_alias(value):
    key = str(value or "").lower().replace(" ", "_")
    aliases = {
        "mean": "IC 均值",
        "std": "IC 标准差",
        "ir": "信息比率",
        "t_stat": "t 统计量",
        "max": "最大 IC",
        "min": "最小 IC",
        "ac1": "一阶自相关",
        "half_life": "半衰期",
        "sharpe": "夏普比率",
        "sharpe_ratio": "夏普比率",
        "annual_return": "年化收益率",
        "annualized_return": "年化收益率",
        "max_drawdown": "最大回撤",
        "total_return": "总收益率",
        "observations": "有效观测数",
        "success": "运行成功",
    }
    return aliases.get(key, "其他统计指标")


def group_alias(value):
    text = str(value or "").lower()
    aliases = {
        "day": "日盘",
        "night": "夜盘",
        "long-short": "多空组合",
        "long_short": "多空组合",
    }
    return aliases.get(text, "回测组合")
