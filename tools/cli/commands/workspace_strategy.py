"""CLI commands for strategies owned by the active test workspace."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state


def register_workspace_strategy_commands(workspace: click.Group) -> None:
    @workspace.group("strategy")
    def strategy_workspace() -> None:
        """管理当前测试配置中的临时策略绑定。"""

    @strategy_workspace.command("list")
    @friendly_errors
    def list_workspace_strategies() -> None:
        state = _state()
        click.echo(json.dumps(
            client_from_config().list_configuration_strategies(state.workspace_id),
            ensure_ascii=False, indent=2, sort_keys=True,
        ))

    @strategy_workspace.command("add-inline")
    @click.option("--name", required=True)
    @click.option("--source-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--entrypoint", default="Strategy", show_default=True)
    @click.option("--target-strategy-id", required=True)
    @friendly_errors
    def add_inline(name: str, source_file: Path, entrypoint: str, target_strategy_id: str) -> None:
        state = _state()
        value = client_from_config().add_inline_strategy(
            state.workspace_id,
            expected_revision=state.configuration_revision,
            name=name,
            source_code=source_file.read_text(encoding="utf-8"),
            entrypoint=entrypoint,
            target_strategy_id=target_strategy_id,
        )
        _save_revision(state, value)
        click.echo(json.dumps(value.get("change") or value, ensure_ascii=False, indent=2))

    @strategy_workspace.command("bind-library")
    @click.option("--strategy-ref", required=True)
    @click.option("--revision-ref", required=True)
    @click.option("--target-strategy-id", required=True)
    @click.option("--source-sha256", default="")
    @friendly_errors
    def bind_library(strategy_ref: str, revision_ref: str, target_strategy_id: str, source_sha256: str) -> None:
        state = _state()
        value = client_from_config().bind_library_strategy(
            state.workspace_id,
            expected_revision=state.configuration_revision,
            strategy_ref=strategy_ref,
            revision_ref=revision_ref,
            target_strategy_id=target_strategy_id,
            source_sha256=source_sha256,
        )
        _save_revision(state, value)
        click.echo(json.dumps(value.get("change") or value, ensure_ascii=False, indent=2))

    @strategy_workspace.command("unbind")
    @click.argument("binding_id")
    @friendly_errors
    def unbind(binding_id: str) -> None:
        state = _state()
        value = client_from_config().remove_configuration_strategy(
            state.workspace_id, binding_id,
            expected_revision=state.configuration_revision,
        )
        _save_revision(state, value)
        click.echo(json.dumps(value.get("change") or value, ensure_ascii=False, indent=2))


def _state():
    state = load_state()
    if not state.workspace_id:
        raise click.ClickException("尚未选择测试配置工作区；请先运行 factortester workspace create/use")
    return state


def _save_revision(state, response: dict) -> None:
    configuration = response.get("configuration") or {}
    if "revision" in configuration:
        state.configuration_revision = int(configuration["revision"])
        save_state(state)
