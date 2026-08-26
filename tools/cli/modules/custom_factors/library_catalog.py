"""CLI presentation for the Manager-owned factor business catalog."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table

FACTOR_SCOPES = ("public", "mine", "subordinates")
FACTOR_SET_SCOPES = ("mine", "subordinates")


def register_factor_library_catalog_commands(group: click.Group) -> None:
    group.add_command(families)
    group.add_command(factors)
    group.add_command(factor_sets)


def _scope_items(
    payload: dict[str, Any],
    *,
    envelope: str,
    item_key: str | None,
    scope: str,
    allowed_scopes: tuple[str, ...],
) -> list[dict[str, Any]]:
    scopes = payload.get(envelope)
    if not isinstance(scopes, dict):
        return []
    selected = allowed_scopes if scope == "all" else (scope,)
    result: list[dict[str, Any]] = []
    for key in selected:
        value = scopes.get(key)
        if item_key is not None:
            value = value.get(item_key) if isinstance(value, dict) else []
        if isinstance(value, list):
            result.extend(dict(item) for item in value if isinstance(item, dict))
    return result


def _matches(item: dict[str, Any], query: str) -> bool:
    needle = str(query or "").strip().casefold()
    if not needle:
        return True
    return any(
        needle in str(value or "").casefold()
        for value in item.values()
        if isinstance(value, (str, int, float))
    )


def _result(
    *, object_type: str, scope: str, items: list[dict[str, Any]],
    available_scopes: tuple[str, ...], query: str = "",
) -> dict[str, Any]:
    filtered = [item for item in items if _matches(item, query)]
    return {
        "schema_version": 1,
        "object_type": object_type,
        "scope": scope,
        "available_scopes": list(available_scopes),
        "query": str(query or ""),
        "count": len(filtered),
        "items": filtered,
    }


def _emit(
    value: dict[str, Any],
    *,
    columns: tuple[tuple[str, str], ...],
    as_json: bool,
) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    items = value["items"]
    if not items:
        click.echo("暂无符合条件的目录条目")
        return
    rows = [tuple(item.get(key) or "" for key, _label in columns) for item in items]
    for line in render_table(
        tuple(label for _key, label in columns), rows, max_widths=(42,) * len(columns),
    ):
        click.echo(line)


def _catalog_command(
    *,
    object_type: str,
    item_key: str,
    columns: tuple[tuple[str, str], ...],
) -> Callable[..., None]:
    @click.option(
        "--scope",
        type=click.Choice(("all", *FACTOR_SCOPES)),
        default="all",
        show_default=True,
    )
    @click.option(
        "--query",
        default="",
        help="仅筛选当前响应中的显示条目，不改变权限范围。",
    )
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def command(scope: str, query: str, as_json: bool) -> None:
        payload = client_from_config().factor_catalog()
        items = _scope_items(
            payload,
            envelope="family_scopes",
            item_key=item_key,
            scope=scope,
            allowed_scopes=FACTOR_SCOPES,
        )
        _emit(
            _result(
                object_type=object_type,
                scope=scope,
                items=items,
                available_scopes=FACTOR_SCOPES,
                query=query,
            ),
            columns=columns,
            as_json=as_json,
        )
    return command


families = click.command("families")(_catalog_command(
    object_type="factor_family",
    item_key="families",
    columns=(
        ("factor_family_alias", "因子家族"),
        ("chinese_name", "名称"),
        ("owner_alias", "所有者"),
        ("factor_count", "因子数"),
    ),
))
families.help = "列出与 Web/Swift 相同权限范围内的因子家族。"


factors = click.command("factors")(_catalog_command(
    object_type="factor",
    item_key="factors",
    columns=(
        ("factor_alias", "因子"),
        ("factor_family_alias", "因子家族"),
        ("owner_alias", "所有者"),
        ("product_group", "产品组"),
    ),
))
factors.help = "列出与 Web/Swift 相同权限范围内的已登记因子。"


@click.command("factor-sets")
@click.option(
    "--scope",
    type=click.Choice(("all", *FACTOR_SET_SCOPES)),
    default="all",
    show_default=True,
)
@click.option("--query", default="", help="由 Manager 搜索因子集合。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def factor_sets(scope: str, query: str, as_json: bool) -> None:
    """列出与 Web/Swift 相同权限范围内的因子集合。"""
    payload = client_from_config().factor_set_catalog(query=query)
    items = _scope_items(
        payload,
        envelope="item_scopes",
        item_key=None,
        scope=scope,
        allowed_scopes=FACTOR_SET_SCOPES,
    )
    _emit(
        _result(
            object_type="factor_set",
            scope=scope,
            items=items,
            available_scopes=FACTOR_SET_SCOPES,
            query=query,
        ),
        columns=(
            ("title_zh", "因子集合"),
            ("owner_username", "所有者"),
            ("member_count", "因子数"),
            ("target_ref", "引用"),
        ),
        as_json=as_json,
    )
