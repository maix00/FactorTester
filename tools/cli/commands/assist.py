"""Atomically exchange one structured document with the active assisted page."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.agent_auth import load_capability
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _profile_id(requested: str) -> str:
    capability = load_capability()
    value = str(requested or "").strip()
    if capability is not None:
        if value and value != capability.profile_id:
            raise click.ClickException("the active capability is signed for another Profile")
        return capability.profile_id
    if not value:
        raise click.ClickException("--profile-id is required outside a Profile Agent runtime")
    return value


def _document(file: Path | None, use_stdin: bool) -> dict:
    if bool(file) == bool(use_stdin):
        raise click.ClickException("choose exactly one of --file or --stdin")
    raw = click.get_text_stream("stdin").read() if use_stdin else file.read_text("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise click.ClickException("assistance document must be a JSON object")
    return value


def _input_options(function):
    function = click.option("--stdin", "use_stdin", is_flag=True)(function)
    return click.option("--file", type=click.Path(path_type=Path, exists=True))(function)


@click.group("assist")
@click.option("--profile-id", default="", hidden=True)
@click.pass_context
def assist(context: click.Context, profile_id: str) -> None:
    """Inspect or atomically fill the page currently assisted by this Agent."""
    # Resolve the capability only when a command executes so Click can render
    # subcommand help in an ordinary shell without an Agent runtime.
    context.obj = profile_id


@assist.command("inspect")
@click.pass_obj
@friendly_errors
def inspect(profile_id: str) -> None:
    profile_id = _profile_id(profile_id)
    value = client_from_config().inspect_profile_agent_assistance(profile_id)
    click.echo(json.dumps(value.get("page"), ensure_ascii=False, indent=2))


@assist.command("validate")
@_input_options
@click.pass_obj
@friendly_errors
def validate(profile_id: str, file: Path | None, use_stdin: bool) -> None:
    profile_id = _profile_id(profile_id)
    client_from_config().validate_profile_agent_assistance(
        profile_id, _document(file, use_stdin),
    )
    click.echo("Assistance document is valid")


@assist.command("apply")
@_input_options
@click.option("--tab-id", required=True)
@click.option("--expected-revision", required=True, type=click.IntRange(min=0))
@click.pass_obj
@friendly_errors
def apply(
    profile_id: str, file: Path | None, use_stdin: bool,
    tab_id: str, expected_revision: int,
) -> None:
    profile_id = _profile_id(profile_id)
    client_from_config().apply_profile_agent_assistance(
        profile_id, tab_id=tab_id, expected_revision=expected_revision,
        document=_document(file, use_stdin),
    )
    click.echo("Assistance document applied")
