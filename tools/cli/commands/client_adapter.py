"""Provider-neutral local client profile and adapter commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.adapters import ClientAdapterManager
from tools.cli.release.profile import load_profile_root


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@click.group("adapter")
def client_adapter() -> None:
    """Manage signed local adapters without LLM or database calls."""


def _root_option(function):
    return click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )(function)


def _profile_option(function):
    return click.option("--profile-id", default="")(function)


@client_adapter.command("list")
@_profile_option
@_root_option
@friendly_errors
def list_adapters(release_profile: Path | None, profile_id: str) -> None:
    click.echo(_json(
        ClientAdapterManager(
            load_profile_root(release_profile),
            profile_id=profile_id,
        ).list()
    ))


def _adapter_action(name: str):
    def decorator(function):
        command = client_adapter.command(name)(function)
        command = click.argument("adapter_id")(command)
        command = _profile_option(command)
        return _root_option(command)
    return decorator


@_adapter_action("status")
@friendly_errors
def adapter_status(
    adapter_id: str,
    release_profile: Path | None,
    profile_id: str,
) -> None:
    click.echo(_json(
        ClientAdapterManager(
            load_profile_root(release_profile), profile_id=profile_id
        ).status(
            adapter_id
        )
    ))


@_adapter_action("start")
@friendly_errors
def adapter_start(
    adapter_id: str,
    release_profile: Path | None,
    profile_id: str,
) -> None:
    click.echo(_json(
        ClientAdapterManager(
            load_profile_root(release_profile), profile_id=profile_id
        ).start(
            adapter_id
        )
    ))


@_adapter_action("stop")
@friendly_errors
def adapter_stop(
    adapter_id: str,
    release_profile: Path | None,
    profile_id: str,
) -> None:
    click.echo(_json(
        ClientAdapterManager(
            load_profile_root(release_profile), profile_id=profile_id
        ).stop(
            adapter_id
        )
    ))


@_adapter_action("open")
@friendly_errors
def adapter_open(
    adapter_id: str,
    release_profile: Path | None,
    profile_id: str,
) -> None:
    click.echo(_json(
        ClientAdapterManager(
            load_profile_root(release_profile), profile_id=profile_id
        ).open(
            adapter_id
        )
    ))
