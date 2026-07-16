"""Backtest results subcommand handlers.

This module owns the result-inspection command output.  The main controller
keeps only dispatch and state loading, while result-specific fetching,
aggregation, and tables live here with the result data/view helpers.
"""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.modules.backtest import results_data as results_data_formatter
from tools.cli.modules.backtest import results_views as results_view_formatter
from tools.cli.modules.backtest.run_output import _chart_body_width, _multi_series_chart, _result_series
from tools.cli.table import render_table


def print_results_help() -> None:
    for line in results_view_formatter.results_help_lines():
        click.echo(line)


def dispatch_stored_result_command(state, action: str, args: tuple[str, ...]) -> None:
    if action == "summary":
        print_stored_result_summary(state)
        return
    if action == "equity":
        print_stored_equity_chart(state)
        return
    if action in {"attribution", "attr"}:
        print_attribution_result(state, args)
        return
    if action in {"ledgers", "ledger", "cash-pools", "cash-pool"}:
        print_ledger_replay_result(state, args)
        return
    if action == "detail":
        print_group_detail_result(state, args)
        return
    if action in {"ranking", "rank"}:
        print_group_ranking_result(state, args)
        return
    if action == "snapshot":
        print_snapshot_result(state, args)
        return
    if action in {"order-flow", "orders"}:
        print_order_flow_result(state, args)
        return
    raise click.ClickException("results 支持: summary, equity, attribution, ledgers, detail, ranking, snapshot, order-flow")


def require_last_result(state) -> dict[str, Any]:
    if not state.backtest_last_result:
        raise click.ClickException("没有最近一次 backtest 结果；请先运行 factortester backtest --run")
    return state.backtest_last_result


def print_stored_result_summary(state) -> None:
    data = require_last_result(state)
    series = _result_series(data.get("groups") or [])
    rows = [
        (f"{name} · LS" if is_ls else name, f"{curve[-1]:.2f}", len(curve))
        for name, curve, is_ls in series
        if curve
    ]
    click.echo("最近一次回测摘要")
    for line in render_table(("策略", "最终权益", "点数"), rows, indent="  ", aligns=("left", "right", "right"), max_widths=(28, 16, 8)):
        click.echo(line)


def print_stored_equity_chart(state) -> None:
    data = require_last_result(state)
    series = _result_series(data.get("groups") or [])
    if not series:
        raise click.ClickException("最近一次结果没有可画的净值曲线")
    for line in ["净值曲线:", *_multi_series_chart(series, width=_chart_body_width())]:
        click.echo(line)


def print_attribution_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    groups = _selected_result_groups(data, _arg_value(args, "--group-name"))
    if not groups:
        raise click.ClickException("最近一次结果中找不到可归因的策略")
    by = (_arg_value(args, "--by") or "").strip().lower()
    top_raw = _arg_value(args, "--top")
    top_n = int(top_raw) if top_raw else 10
    rows = []
    bucket_fee: dict[str, float] = {}
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        curve = _group_equity_curve(group)
        initial = curve[0] if curve else 0.0
        final = curve[-1] if curve else 0.0
        flow = _fetch_order_flow_for_group(state, data, name)
        fee_sum = 0.0
        for record in flow:
            fee = _float(record.get("fee_cost") or record.get("fee") or 0.0)
            fee_sum += fee
            bucket = _attribution_bucket(record, by)
            if bucket:
                bucket_fee[bucket] = bucket_fee.get(bucket, 0.0) + fee
        net_return = final / initial - 1.0 if initial else 0.0
        fee_return = fee_sum / initial if initial else 0.0
        gross_return = net_return + fee_return
        rows.append((
            name,
            _pct(gross_return),
            _pct(-fee_return),
            _pct(net_return),
            f"{final:,.2f}",
            f"{fee_sum:,.2f}",
            len(flow),
        ))
    click.echo("归因摘要")
    for line in render_table(
        ("策略", "gross", "fee", "net", "最终权益", "费用", "订单流"),
        rows,
        indent="  ",
        aligns=("left", "right", "right", "right", "right", "right", "right"),
        max_widths=(28, 10, 10, 10, 16, 16, 8),
    ):
        click.echo(line)
    if by in {"product", "products", "contract", "contracts", "ledger", "ledgers", "cash-pool", "cash_pool", "cashpool"}:
        table = sorted(bucket_fee.items(), key=lambda item: abs(item[1]), reverse=True)
        if top_n > 0:
            table = table[:top_n]
        click.echo("")
        click.echo(_attribution_table_title(by))
        for line in render_table(
            (_attribution_table_header(by), "费用"),
            [(bucket, f"{fee:,.2f}") for bucket, fee in table],
            indent="  ",
            aligns=("left", "right"),
            max_widths=(32, 16),
        ):
            click.echo(line)


def print_ledger_replay_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    groups = _selected_result_groups(data, _arg_value(args, "--group-name"))
    if not groups:
        raise click.ClickException("最近一次结果中找不到可汇总的策略")
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        for record in _fetch_order_flow_for_group(state, data, name):
            ledger_id = _record_ledger_id(record)
            cash_pool_id = _record_cash_pool_id(record)
            if not ledger_id and not cash_pool_id:
                continue
            key = (name, ledger_id or "(未记录账本)", cash_pool_id or "(未记录资金池)")
            row = rows_by_key.setdefault(key, {
                "records": 0,
                "fee": 0.0,
                "last_cash": "",
                "last_margin": "",
            })
            row["records"] += 1
            row["fee"] += _float(record.get("fee_cost") or record.get("fee") or 0.0)
            cash_after = _fmt_detail_number(record, "cash_after")
            if cash_after:
                row["last_cash"] = cash_after
            margin_after = _fmt_detail_number(record, "margin_after")
            if margin_after:
                row["last_margin"] = margin_after
    click.echo("Ledger 回放摘要")
    if not rows_by_key:
        click.echo("  最近一次 order-flow 没有记录 ledger/cash pool 信息；请重新运行回测以生成新的成交落账 trace。")
        return
    rows = [
        (
            strategy,
            ledger_id,
            cash_pool_id,
            values["records"],
            f"{values['fee']:,.2f}",
            values["last_cash"],
            values["last_margin"],
        )
        for (strategy, ledger_id, cash_pool_id), values in sorted(rows_by_key.items())
    ]
    for line in render_table(
        ("策略", "账本", "资金池", "记录数", "费用", "最后现金", "最后保证金"),
        rows,
        indent="  ",
        aligns=("left", "left", "left", "right", "right", "right", "right"),
        max_widths=(20, 22, 22, 8, 14, 16, 16),
    ):
        click.echo(line)


def print_group_detail_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    group_name = _arg_value(args, "--group-name")
    if not group_name:
        raise click.ClickException("detail 需要 --group-name NAME")
    group = _result_group_for_name(data, group_name)
    if not group:
        raise click.ClickException(f"最近一次结果中找不到策略: {group_name}")
    payload = _group_detail_payload(state, data, group)
    detail = client_from_config().group_detail(payload).get("detail") or {}
    product_analysis = detail.get("product_analysis") or {}
    level = (_arg_value(args, "--level") or product_analysis.get("default_level") or "products").lower()
    if level in {"product", "products"}:
        analysis = (product_analysis.get("by_level") or {}).get("products") or product_analysis
        title = "产品层级贡献"
    elif level in {"contract", "contracts"}:
        analysis = (product_analysis.get("by_level") or {}).get("contracts") or product_analysis
        title = "合约层级贡献"
    else:
        raise click.ClickException("--level 只能是 product 或 contract")
    rows = []
    for row in list(analysis.get("rows") or [])[:20]:
        product = row.get("product") or {}
        product_label = _product_display(product)
        fee = product.get("fee") or {}
        market_rule = row.get("market_rule") or {}
        rows.append((
            product_label,
            _pct(_float(row.get("gross_contribution"))),
            str(row.get("active_period_count") or ""),
            _fmt_optional(fee.get("open")),
            _fmt_optional(fee.get("close_today")),
            _fmt_optional(market_rule.get("multiplier")),
            _fmt_optional(market_rule.get("margin_ratio")),
        ))
    click.echo(f"{group_name} · {title}")
    for line in render_table(
        ("产品", "gross贡献", "活跃期", "开仓费", "平今费", "乘数", "保证金率"),
        rows,
        indent="  ",
        aligns=("left", "right", "right", "right", "right", "right", "right"),
        max_widths=(32, 12, 8, 10, 10, 8, 10),
    ):
        click.echo(line)
    concentration = []
    if analysis.get("top1_positive_contribution_ratio") is not None:
        concentration.append(f"top1正贡献占比={_pct(_float(analysis.get('top1_positive_contribution_ratio')))}")
    if analysis.get("top3_positive_contribution_ratio") is not None:
        concentration.append(f"top3正贡献占比={_pct(_float(analysis.get('top3_positive_contribution_ratio')))}")
    if concentration:
        click.echo("  " + " · ".join(concentration))


def print_group_ranking_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    product_path_selection_id = str(data.get("product_path_selection_id") or "")
    if not product_path_selection_id:
        raise click.ClickException("最近一次结果没有 product_path_selection_id，无法请求排序分析")
    detail = client_from_config().group_ranking_detail({
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
        "job_id": data.get("job_id") or "",
        "run_id": data.get("run_id") or data.get("run_token") or "",
    }).get("detail") or {}
    rows = []
    for key, value in sorted(detail.items()):
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append((key, _fmt_optional(value)))
    click.echo("分组排序能力摘要")
    if rows:
        for line in render_table(("字段", "值"), rows, indent="  ", max_widths=(32, 48)):
            click.echo(line)
    else:
        click.echo("  后端返回了排序分析对象；当前 CLI 只显示标量摘要，可用 web overlay 查看完整图表。")


def print_snapshot_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    product_path_selection_id = str(data.get("product_path_selection_id") or "")
    if not product_path_selection_id:
        raise click.ClickException("最近一次结果没有 product_path_selection_id，无法请求快照")
    timestamp_ms = _result_timestamp_ms(data, args)
    result = client_from_config().group_snapshot({
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
        "timestamp_ms": timestamp_ms,
        "job_id": data.get("job_id") or "",
        "run_id": data.get("run_id") or data.get("run_token") or "",
    })
    summary = result.get("summary") or {}
    click.echo(f"快照: timestamp_ms={result.get('timestamp_ms')}")
    click.echo(f"事件: {result.get('event_label') or result.get('event_type') or '（未知）'}")
    click.echo(f"摘要: changed={summary.get('total_changed')} products={summary.get('total_prod_count')} turnover={summary.get('avg_turnover')}")
    matrices = result.get("matrices") if isinstance(result.get("matrices"), list) else []
    for matrix in matrices[:1]:
        columns_raw = matrix.get("columns") if isinstance(matrix, dict) else []
        rows_raw = matrix.get("rows") if isinstance(matrix, dict) else []
        columns = columns_raw if isinstance(columns_raw, list) else []
        rows = rows_raw if isinstance(rows_raw, list) else []
        click.echo(f"矩阵: {matrix.get('label') if isinstance(matrix, dict) else ''} · 列={len(columns)} · 行={len(rows)}")


def print_order_flow_result(state, args: tuple[str, ...]) -> None:
    data = require_last_result(state)
    payload: dict[str, Any] = {
        "page_uuid": state.page_uuid,
        "job_id": data.get("job_id") or "",
        "run_id": data.get("run_id") or data.get("run_token") or "",
    }
    group_name = _arg_value(args, "--group-name")
    if group_name:
        group_id = _group_id_for_name(data, group_name)
        if group_id:
            payload["group_id"] = group_id
        else:
            raise click.ClickException(f"最近一次结果中找不到策略: {group_name}")
    timestamp_ms = _arg_value(args, "--timestamp-ms")
    if timestamp_ms:
        payload["timestamp_ms"] = int(timestamp_ms)
    order_id = _arg_value(args, "--order-id")
    if order_id:
        payload["order_id"] = order_id
    result = client_from_config().group_order_flow(payload)
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []

    counts_only = "--counts-only" in args
    limit_raw = _arg_value(args, "--limit")
    limit = int(limit_raw) if limit_raw else 20
    ledger_filter = _arg_value(args, "--ledger")
    cash_pool_filter = _arg_value(args, "--cash-pool") or _arg_value(args, "--cash_pool")

    filtered_groups = []
    total_records = 0
    for group in groups:
        if not isinstance(group, dict):
            continue
        records = list(group.get("records") or [])
        if ledger_filter:
            records = [record for record in records if _record_ledger_id(record) == ledger_filter]
        if cash_pool_filter:
            records = [record for record in records if _record_cash_pool_id(record) == cash_pool_filter]
        group_copy = dict(group)
        group_copy["records"] = records
        filtered_groups.append(group_copy)
        total_records += len(records)
    groups = filtered_groups
    if ledger_filter or cash_pool_filter:
        filters = []
        if ledger_filter:
            filters.append(f"ledger={ledger_filter}")
        if cash_pool_filter:
            filters.append(f"cash_pool={cash_pool_filter}")
        click.echo(f"订单流: records={total_records} ({', '.join(filters)})")
    else:
        click.echo(f"订单流: records={result.get('record_count', 0)}")

    rows = []
    for group in groups:
        records = group.get("records") if isinstance(group, dict) else []
        rows.append((group.get("group_name") or group.get("group_id") or "", len(records or [])))
    for line in render_table(("策略", "记录数"), rows, indent="  ", aligns=("left", "right"), max_widths=(28, 8)):
        click.echo(line)

    if counts_only:
        return

    for group in groups:
        records = list(group.get("records") or []) if isinstance(group, dict) else []
        if not records:
            continue
        name = group.get("group_name") or group.get("group_id") or ""
        shown = records if limit <= 0 else records[:limit]
        click.echo(f"\n{name} 订单流明细 (显示 {len(shown)}/{len(records)} 条):")
        show_fee = (_arg_value(args, "--show") == "fee") or ("--show-fee" in args)
        if show_fee:
            detail_rows = [
                (
                    str(r.get("timestamp") or ""),
                    str(r.get("product") or ""),
                    str(r.get("step") or ""),
                    f"{_float(r.get('quantity')):.4g}",
                    "" if r.get("effective_price") is None else f"{_float(r.get('effective_price')):.6g}",
                    f"{_float(r.get('fee_cost')):,.2f}",
                    _record_ledger_id(r),
                    _record_cash_pool_id(r),
                    _fmt_detail_number(r, "cash_after"),
                    _fmt_detail_number(r, "margin_after"),
                    str(r.get("status") or ""),
                )
                for r in shown
            ]
            headers = ("时间", "品种", "步骤", "数量", "成交价", "费用", "账本", "资金池", "现金", "保证金", "状态")
            widths = (24, 16, 14, 10, 10, 12, 16, 16, 14, 14, 10)
            aligns = ("left", "left", "left", "right", "right", "right", "left", "left", "right", "right", "left")
        else:
            detail_rows = [
                (
                    str(r.get("timestamp") or ""),
                    str(r.get("product") or ""),
                    str(r.get("step") or ""),
                    str(r.get("label") or ""),
                    f"{_float(r.get('quantity')):.4g}",
                    "" if r.get("effective_price") is None else f"{_float(r.get('effective_price')):.6g}",
                    str(r.get("status") or ""),
                    str(r.get("reject_reason") or ""),
                )
                for r in shown
            ]
            headers = ("时间", "品种", "步骤", "说明", "数量", "成交价", "状态", "拒绝原因")
            widths = (24, 14, 14, 16, 10, 10, 10, 20)
            aligns = ("left", "left", "left", "left", "right", "right", "left", "left")
        for line in render_table(headers, detail_rows, indent="  ", aligns=aligns, max_widths=widths):
            click.echo(line)
        if limit > 0 and len(records) > limit:
            click.echo(f"  ... 还有 {len(records) - limit} 条，用 --limit 0 查看全部")


def _result_timestamp_ms(data: dict[str, Any], args: tuple[str, ...]) -> int:
    return results_data_formatter.result_timestamp_ms(data, args, error=click.ClickException)


def _selected_result_groups(data: dict[str, Any], group_name: str = "") -> list[dict[str, Any]]:
    return results_data_formatter.selected_result_groups(data, group_name)


def _result_group_for_name(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    return results_data_formatter.result_group_for_name(data, name)


def _group_equity_curve(group: dict[str, Any]) -> list[float]:
    return results_data_formatter.group_equity_curve(group)


def _fetch_order_flow_for_group(state, data: dict[str, Any], group_name: str) -> list[dict[str, Any]]:
    group_id = _group_id_for_name(data, group_name)
    if not group_id:
        return []
    result = client_from_config().group_order_flow({
        "page_uuid": state.page_uuid,
        "group_id": group_id,
        "job_id": data.get("job_id") or "",
        "run_id": data.get("run_id") or data.get("run_token") or "",
    })
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    if not groups:
        return []
    return list(groups[0].get("records") or [])


def _attribution_bucket(record: dict[str, Any], by: str) -> str:
    return results_data_formatter.attribution_bucket(record, by)


def _attribution_table_title(by: str) -> str:
    return results_data_formatter.attribution_table_title(by)


def _attribution_table_header(by: str) -> str:
    return results_data_formatter.attribution_table_header(by)


def _record_ledger_id(record: dict[str, Any]) -> str:
    return results_data_formatter.record_ledger_id(record)


def _record_cash_pool_id(record: dict[str, Any]) -> str:
    return results_data_formatter.record_cash_pool_id(record)


def _group_detail_payload(state, data: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    return results_data_formatter.group_detail_payload(state, data, group, error=click.ClickException)


def _product_display(product: Any) -> str:
    return results_data_formatter.product_display(product)


def _float(value: Any) -> float:
    return results_data_formatter.as_float(value)


def _pct(value: float) -> str:
    return results_data_formatter.pct(value)


def _fmt_optional(value: Any) -> str:
    return results_data_formatter.fmt_optional(value)


def _fmt_detail_number(record: dict[str, Any], key: str) -> str:
    return results_data_formatter.fmt_detail_number(record, key)


def _group_id_for_name(data: dict[str, Any], name: str) -> str:
    return results_data_formatter.group_id_for_name(data, name)


def _arg_value(args: tuple[str, ...], flag: str) -> str:
    return results_data_formatter.arg_value(args, flag)
