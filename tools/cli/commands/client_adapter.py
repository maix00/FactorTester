"""Provider-neutral local client profile and adapter commands."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.adapters import ClientAdapterManager
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
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


@client_adapter.command("list")
@_root_option
@friendly_errors
def list_adapters(release_profile: Path | None) -> None:
    click.echo(_json(
        ClientAdapterManager(load_profile_root(release_profile)).list()
    ))


def _adapter_action(name: str):
    def decorator(function):
        command = client_adapter.command(name)(function)
        command = click.argument("adapter_id")(command)
        return _root_option(command)
    return decorator


@_adapter_action("status")
@friendly_errors
def adapter_status(adapter_id: str, release_profile: Path | None) -> None:
    click.echo(_json(
        ClientAdapterManager(load_profile_root(release_profile)).status(
            adapter_id
        )
    ))


@_adapter_action("start")
@friendly_errors
def adapter_start(adapter_id: str, release_profile: Path | None) -> None:
    click.echo(_json(
        ClientAdapterManager(load_profile_root(release_profile)).start(
            adapter_id
        )
    ))


@_adapter_action("stop")
@friendly_errors
def adapter_stop(adapter_id: str, release_profile: Path | None) -> None:
    click.echo(_json(
        ClientAdapterManager(load_profile_root(release_profile)).stop(
            adapter_id
        )
    ))


@_adapter_action("open")
@friendly_errors
def adapter_open(adapter_id: str, release_profile: Path | None) -> None:
    click.echo(_json(
        ClientAdapterManager(load_profile_root(release_profile)).open(
            adapter_id
        )
    ))


@click.group("profile")
def client_profile() -> None:
    """Manage version-independent local user profiles."""


@client_profile.command("init")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option("--server-url", required=True)
@click.option(
    "--workspace-root",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def initialize_profile(
    profile_id: str,
    display_name: str,
    server_url: str,
    workspace_root: Path,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    click.echo(_json(store.save(new_local_profile(
        profile_id=profile_id,
        display_name=display_name,
        server_url=server_url,
        workspace_root=workspace_root,
    ))))


@client_profile.command("list")
@_root_option
@friendly_errors
def list_profiles(release_profile: Path | None) -> None:
    click.echo(_json(
        LocalProfileStore(load_profile_root(release_profile)).list()
    ))
