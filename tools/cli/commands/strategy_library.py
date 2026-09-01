"""CLI for persistent, versioned Strategy library entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.commands.strategy_output import emit_library


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
    emit_library(value, as_json)


@strategy_library.command("show")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def show_library(strategy_ref: str, as_json: bool) -> None:
    value = client_from_config().get_strategy(strategy_ref, include_source=False)
    emit_library(value, as_json)


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
    emit_library(value, as_json)


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
    emit_library(client_from_config().update_strategy(strategy_ref, values), as_json)


@strategy_library.command("delete")
@click.argument("strategy_ref")
@click.option("--yes", is_flag=True, help="确认归档该策略。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def delete_library(strategy_ref: str, yes: bool, as_json: bool) -> None:
    if not yes:
        raise click.ClickException("删除是归档操作；请显式指定 --yes")
    emit_library(client_from_config().delete_strategy(strategy_ref), as_json)


@strategy_library.group("revisions")
def revisions() -> None:
    """查看策略的不可变源码版本。"""


@revisions.command("list")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_revisions(strategy_ref: str, as_json: bool) -> None:
    emit_library(client_from_config().list_strategy_revisions(strategy_ref), as_json)


@revisions.command("show")
@click.argument("strategy_ref")
@click.argument("revision_ref")
@click.option("--with-source", is_flag=True, help="按需输出源码。")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_revision(
    strategy_ref: str, revision_ref: str, with_source: bool, as_json: bool,
) -> None:
    emit_library(client_from_config().get_strategy_revision(
        strategy_ref, revision_ref, include_source=with_source,
    ), as_json)


@strategy_library.group("share")
def share() -> None:
    """管理策略的显式共享关系。"""


@share.command("list")
@click.argument("strategy_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_shares(strategy_ref: str, as_json: bool) -> None:
    emit_library(client_from_config().list_strategy_shares(strategy_ref), as_json)


@share.command("grant")
@click.argument("strategy_ref")
@click.argument("principal_ref")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def grant_share(strategy_ref: str, principal_ref: str, as_json: bool) -> None:
    emit_library(
        client_from_config().grant_strategy_share(strategy_ref, principal_ref),
        as_json,
    )


@share.command("revoke")
@click.argument("strategy_ref")
@click.argument("principal_ref")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def revoke_share(strategy_ref: str, principal_ref: str, as_json: bool) -> None:
    emit_library(
        client_from_config().revoke_strategy_share(strategy_ref, principal_ref),
        as_json,
    )
