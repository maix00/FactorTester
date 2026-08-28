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
            raise click.ClickException(
                "the active capability is signed for another Profile"
            )
        return capability.profile_id
    if not value:
        raise click.ClickException(
            "--profile-id is required outside a Profile Agent runtime"
        )
    return value


def _document(file: Path | None, use_stdin: bool) -> dict:
    if bool(file) == bool(use_stdin):
        raise click.ClickException("choose exactly one of --file or --stdin")
    raw = (
        click.get_text_stream("stdin").read() if use_stdin else file.read_text("utf-8")
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise click.ClickException("assistance document must be a JSON object")
    return value


def _input_options(function):
    function = click.option("--stdin", "use_stdin", is_flag=True)(function)
    return click.option("--file", type=click.Path(path_type=Path, exists=True))(
        function
    )


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


@assist.group("drafts")
def drafts() -> None:
    """Retain and apply structured page-assistance drafts."""


@drafts.command("create")
@_input_options
@click.pass_obj
@friendly_errors
def create_draft(profile_id: str, file: Path | None, use_stdin: bool) -> None:
    value = client_from_config().create_profile_agent_assistance_draft(
        _profile_id(profile_id),
        _document(file, use_stdin),
    )
    click.echo(json.dumps(value.get("draft"), ensure_ascii=False, indent=2))


@drafts.command("list")
@click.pass_obj
@friendly_errors
def list_drafts(profile_id: str) -> None:
    value = client_from_config().list_profile_agent_assistance_drafts(
        _profile_id(profile_id),
    )
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


@drafts.command("show")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def show_draft(profile_id: str, draft_id: str) -> None:
    value = client_from_config().get_profile_agent_assistance_draft(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


@drafts.command("validate")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def validate_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().validate_profile_agent_assistance(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo("Assistance draft is valid")


@drafts.command("apply")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def apply_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().apply_profile_agent_assistance(
        _profile_id(profile_id),
        draft_id=draft_id,
    )
    click.echo("Assistance draft applied")


@drafts.command("delete")
@click.argument("draft_id")
@click.pass_obj
@friendly_errors
def delete_draft(profile_id: str, draft_id: str) -> None:
    client_from_config().delete_profile_agent_assistance_draft(
        _profile_id(profile_id),
        draft_id,
    )
    click.echo("Assistance draft deleted")
