"""CLI for persistent, versioned Strategy library entries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


@click.group("strategy-library")
def strategy_library() -> None:
    """管理可复用、可共享且带不可变源码版本的策略。"""


@strategy_library.command("list")
@click.option("--scope", type=click.Choice(["mine", "subordinates", "shared", "all"]), default="mine", show_default=True)
@click.option("--page", type=click.IntRange(1), default=1, show_default=True)
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--query", default="", help="按策略名称或引用搜索。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def list_library(scope: str, page: int, limit: int, query: str, as_json: bool) -> None:
    value = client_from_config().list_strategy_library(
        scope=scope, page=page, limit=limit, query=query,
    )
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for item in value.get("items") or []:
        revision = item.get("current_revision") or {}
        click.echo(
            f"{item.get('strategy_ref')}\t{item.get('name')}\t"
            f"r{revision.get('revision_number', '-')}\t{item.get('visibility')}"
        )


@strategy_library.command("show")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def show_library(strategy_ref: str, as_json: bool) -> None:
    value = client_from_config().get_strategy(strategy_ref)
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    strategy = value.get("strategy") or {}
    click.echo(f"{strategy.get('name')}\t{strategy.get('strategy_ref')}")
    click.echo(f"owner={strategy.get('owner_ref')} visibility={strategy.get('visibility')}")
    revision = strategy.get("current_revision") or {}
    click.echo(f"revision={revision.get('revision_ref')} entrypoint={revision.get('entrypoint')}")
    for hook in revision.get("hooks") or []:
        click.echo(f"hook={hook.get('name')} lines={hook.get('lineno')}-{hook.get('end_lineno')}")


@strategy_library.command("create")
@click.option("--name", required=True)
@click.option("--source-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--entrypoint", default="Strategy", show_default=True)
@click.option("--description", default="")
@click.option("--visibility", type=click.Choice(["private", "shared", "public"]), default="private", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def create_library(
    name: str, source_file: Path, entrypoint: str, description: str,
    visibility: str, as_json: bool,
) -> None:
    value = client_from_config().create_strategy_from_file(
        name=name, source_file=source_file, entrypoint=entrypoint,
        description=description, visibility=visibility,
    )
    _emit(value, as_json)


@strategy_library.command("update")
@click.argument("strategy_ref")
@click.option("--name")
@click.option("--source-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--entrypoint")
@click.option("--description")
@click.option("--visibility", type=click.Choice(["private", "shared", "public"]))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def update_library(
    strategy_ref: str, name: str | None, source_file: Path | None,
    entrypoint: str | None, description: str | None, visibility: str | None,
    as_json: bool,
) -> None:
    values: dict[str, Any] = {
        key: value for key, value in {
            "name": name, "entrypoint": entrypoint,
            "description": description, "visibility": visibility,
        }.items() if value is not None
    }
    if source_file is not None:
        values["source_code"] = source_file.read_text(encoding="utf-8")
    if not values:
        raise click.ClickException("update 至少需要一个修改选项")
    _emit(client_from_config().update_strategy(strategy_ref, values), as_json)


@strategy_library.command("delete")
@click.argument("strategy_ref")
@click.option("--yes", is_flag=True, help="确认归档该策略。")
@friendly_errors
def delete_library(strategy_ref: str, yes: bool) -> None:
    if not yes:
        raise click.ClickException("删除是归档操作；请显式指定 --yes")
    click.echo(json.dumps(
        client_from_config().delete_strategy(strategy_ref),
        ensure_ascii=False, indent=2,
    ))


@strategy_library.group("revisions")
def revisions() -> None:
    """查看策略的不可变源码版本。"""


@revisions.command("list")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_revisions(strategy_ref: str, as_json: bool) -> None:
    _emit(client_from_config().list_strategy_revisions(strategy_ref), as_json)


@revisions.command("show")
@click.argument("strategy_ref")
@click.argument("revision_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_revision(strategy_ref: str, revision_ref: str, as_json: bool) -> None:
    _emit(client_from_config().get_strategy_revision(strategy_ref, revision_ref), as_json)


@strategy_library.group("share")
def share() -> None:
    """管理策略的显式共享关系。"""


@share.command("list")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_shares(strategy_ref: str, as_json: bool) -> None:
    _emit(client_from_config().list_strategy_shares(strategy_ref), as_json)


@share.command("grant")
@click.argument("strategy_ref")
@click.argument("principal_ref")
@friendly_errors
def grant_share(strategy_ref: str, principal_ref: str) -> None:
    _emit(client_from_config().grant_strategy_share(strategy_ref, principal_ref), True)


@share.command("revoke")
@click.argument("strategy_ref")
@click.argument("principal_ref")
@friendly_errors
def revoke_share(strategy_ref: str, principal_ref: str) -> None:
    _emit(client_from_config().revoke_strategy_share(strategy_ref, principal_ref), True)


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                continue
            click.echo(f"{key}={item}")
    else:
        click.echo(str(value))
