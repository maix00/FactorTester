"""Account-owned product-group CLI commands."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.core.json_output import echo_json
from tools.cli.table import render_table


@click.group("groups", invoke_without_command=True)
@click.pass_context
@friendly_errors
def product_groups(ctx: click.Context) -> None:
    """Manage saved product groups."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_product_groups)


@product_groups.command("list")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_product_groups(json_output: bool = False) -> None:
    payload = client_from_config().product_group_catalog()
    groups = payload.get("groups") or []
    if json_output:
        echo_json({"success": True, "groups": groups})
        return
    if not groups:
        click.echo("暂无产品组")
        return
    for group in groups:
        click.echo(product_group_line(group))


@product_groups.command("add")
@click.option("--name", required=True, help="产品组名称。")
@click.option("--path", "paths", multiple=True, required=True, help="产品路径，可重复传入。")
@click.option("--profile-id", default="", help="创建该产品组的研究 Profile。")
@click.option(
    "--research-ref", "research_refs", multiple=True,
    help="该产品组服务的稳定研究引用，可重复传入。",
)
@friendly_errors
def add_product_group(
    name: str,
    paths: tuple[str, ...],
    profile_id: str,
    research_refs: tuple[str, ...],
) -> None:
    group = (client_from_config().create_product_group(
        name=name,
        paths=list(paths),
        profile_id=profile_id,
        research_refs=research_refs,
    ).get("group") or {})
    click.echo("已新增产品组")
    click.echo(product_group_line(group))


@product_groups.group("subjects", invoke_without_command=True)
@click.pass_context
@friendly_errors
def product_group_subjects(ctx: click.Context) -> None:
    """Manage factors and factor sets associated with a product group."""
    if ctx.invoked_subcommand is None:
        click.echo(
            "可用功能: factortester product-library groups subjects list|add|remove"
        )


@product_group_subjects.command("list")
@click.argument("product_group_ref")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_product_group_subjects(
    product_group_ref: str, json_output: bool,
) -> None:
    payload = client_from_config().product_group_subjects(
        product_group_ref=product_group_ref,
    )
    subjects = payload.get("subjects") or {}
    if json_output:
        echo_json({"success": True, "subjects": subjects})
        return
    _echo_product_group_subjects(subjects)


def _subject_change_command(name: str):
    def decorator(function):
        command = product_group_subjects.command(name)(function)
        command = click.argument("product_group_ref")(command)
        command = click.option(
            "--factor-ref", "factor_refs", multiple=True,
            help="稳定因子引用，可重复传入。",
        )(command)
        command = click.option(
            "--factor-set-ref", "factor_set_refs", multiple=True,
            help="稳定因子集合引用，可重复传入。",
        )(command)
        command = click.option(
            "--json", "json_output", is_flag=True, help="输出机器可读 JSON。",
        )(command)
        return friendly_errors(command)
    return decorator


@_subject_change_command("add")
def add_product_group_subjects(
    product_group_ref: str,
    factor_refs: tuple[str, ...],
    factor_set_refs: tuple[str, ...],
    json_output: bool,
) -> None:
    _change_product_group_subjects(
        product_group_ref=product_group_ref,
        action="add",
        factor_refs=factor_refs,
        factor_set_refs=factor_set_refs,
        json_output=json_output,
    )


@_subject_change_command("remove")
def remove_product_group_subjects(
    product_group_ref: str,
    factor_refs: tuple[str, ...],
    factor_set_refs: tuple[str, ...],
    json_output: bool,
) -> None:
    _change_product_group_subjects(
        product_group_ref=product_group_ref,
        action="remove",
        factor_refs=factor_refs,
        factor_set_refs=factor_set_refs,
        json_output=json_output,
    )


def _change_product_group_subjects(
    *,
    product_group_ref: str,
    action: str,
    factor_refs: tuple[str, ...],
    factor_set_refs: tuple[str, ...],
    json_output: bool,
) -> None:
    payload = client_from_config().product_group_subjects(
        product_group_ref=product_group_ref,
        action=action,
        factor_refs=factor_refs,
        factor_set_refs=factor_set_refs,
    )
    subjects = payload.get("subjects") or {}
    if json_output:
        echo_json({"success": True, "subjects": subjects})
        return
    click.echo("产品组关联已更新")
    _echo_product_group_subjects(subjects)


def _echo_product_group_subjects(subjects: dict[str, Any]) -> None:
    click.echo(
        f"产品组: {subjects.get('product_group_name') or ''} "
        f"({subjects.get('product_group_ref') or ''})"
    )
    rows = [
        *(("因子", ref) for ref in subjects.get("factor_refs") or []),
        *(("因子集合", ref) for ref in subjects.get("factor_set_refs") or []),
    ]
    if not rows:
        click.echo("暂无关联因子")
        return
    for line in render_table(("类型", "引用"), rows, max_widths=(16, None)):
        click.echo(line)


def product_group_line(group: dict[str, Any]) -> str:
    name = group.get("name") or group.get("label") or group.get("id")
    group_id = group.get("id") or group.get("product_path_selection_id") or ""
    path_count = group.get("path_count")
    product_count = group.get("product_count")
    parts = [str(name)]
    if group_id:
        parts.append(f"product-group:{group_id}")
    if path_count is not None:
        parts.append(f"{path_count} 路径")
    if product_count is not None:
        parts.append(f"{product_count} 产品")
    return " · ".join(parts)


def product_group_selection(group: dict[str, Any]) -> dict[str, Any]:
    group_id = str(
        group.get("id")
        or group.get("product_path_selection_id")
        or group.get("name")
        or ""
    )
    selection = {
        "product_path_selection_id": group_id,
        "id": group_id,
        "label": group.get("name") or group.get("label") or group_id,
        "product_group": group.get("name") or group.get("product_group") or "",
        "product_group_template_id": group_id,
        "source_type": "user_product_group_template",
    }
    paths = group.get("paths") or group.get("selected_paths")
    if isinstance(paths, list):
        selection["paths"] = list(paths)
        selection["selected_paths"] = list(paths)
    return selection

