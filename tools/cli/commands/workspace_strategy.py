"""CLI commands for strategies owned by the active test workspace."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.state import load_state, save_state
from tools.cli.commands.strategy_output import emit_workspace


def register_workspace_strategy_commands(workspace: click.Group) -> None:
    @workspace.group("strategy")
    def strategy_workspace() -> None:
        """管理当前测试配置中的临时策略绑定。"""

    @strategy_workspace.command("list")
    @click.option("--with-source", is_flag=True, help="按需输出临时策略源码。")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def list_workspace_strategies(with_source: bool, as_json: bool) -> None:
        state = _state()
        emit_workspace(
            client_from_config().list_configuration_strategies(
                state.workspace_id, include_source=with_source,
            ),
            as_json,
        )

    @strategy_workspace.command("show")
    @click.argument("binding_id")
    @click.option("--with-source", is_flag=True, help="按需输出临时策略源码。")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def show_workspace_strategy(
        binding_id: str, with_source: bool, as_json: bool,
    ) -> None:
        state = _state()
        value = client_from_config().list_configuration_strategies(
            state.workspace_id, include_source=with_source,
        )
        binding = next(
            (
                item for item in value.get("bindings") or []
                if str(item.get("binding_id") or "") == binding_id
            ),
            None,
        )
        if binding is None:
            raise click.ClickException(f"未找到策略绑定: {binding_id}")
        result = {"success": True, "binding": binding}
        if (binding.get("source") or {}).get("kind") == "inline":
            temp_ref = (binding.get("source") or {}).get("temp_ref")
            result["strategy"] = next(
                (
                    item for item in value.get("strategies") or []
                    if item.get("temp_ref") == temp_ref
                ),
                None,
            )
        emit_workspace(result, as_json)

    @strategy_workspace.command("add-inline")
    @click.option("--name", required=True)
    @click.option("--source-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--entrypoint", default="Strategy", show_default=True)
    @click.option("--target-strategy-id", required=True)
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def add_inline(
        name: str, source_file: Path, entrypoint: str,
        target_strategy_id: str, as_json: bool,
    ) -> None:
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
        emit_workspace(value.get("change") or value, as_json)

    @strategy_workspace.command("update-inline")
    @click.argument("binding_id")
    @click.option("--name")
    @click.option("--source-file", type=click.Path(
        exists=True, dir_okay=False, path_type=Path,
    ))
    @click.option("--entrypoint")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def update_inline(
        binding_id: str,
        name: str | None,
        source_file: Path | None,
        entrypoint: str | None,
        as_json: bool,
    ) -> None:
        values = {
            key: value for key, value in {
                "name": name,
                "entrypoint": entrypoint,
                "source_code": source_file.read_text(encoding="utf-8")
                if source_file is not None else None,
            }.items() if value is not None
        }
        if not values:
            raise click.ClickException(
                "update-inline 至少需要 --name、--source-file 或 --entrypoint",
            )
        state = _state()
        value = client_from_config().update_inline_strategy(
            state.workspace_id,
            binding_id,
            expected_revision=state.configuration_revision,
            values=values,
        )
        _save_revision(state, value)
        emit_workspace(value.get("change") or value, as_json)

    @strategy_workspace.command("bind-library")
    @click.option("--strategy-ref", required=True)
    @click.option("--revision-ref", required=True)
    @click.option("--target-strategy-id", required=True)
    @click.option("--source-sha256", default="")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def bind_library(
        strategy_ref: str, revision_ref: str, target_strategy_id: str,
        source_sha256: str, as_json: bool,
    ) -> None:
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
        emit_workspace(value.get("change") or value, as_json)

    @strategy_workspace.command("unbind")
    @click.argument("binding_id")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def unbind(binding_id: str, as_json: bool) -> None:
        state = _state()
        value = client_from_config().remove_configuration_strategy(
            state.workspace_id, binding_id,
            expected_revision=state.configuration_revision,
        )
        _save_revision(state, value)
        emit_workspace(value.get("change") or value, as_json)


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
