"""Public deterministic client install, update, status, and rollback."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import load_profile_root, load_release_inputs
from tools.cli.release.transaction import ClientReleaseStore
from tools.cli.commands.client_adapter import client_adapter
from tools.cli.commands.client_profile import client_profile


def _echo(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"current={value.get('current_version') or '-'} "
        f"target={value.get('target_version') or '-'} "
        f"healthy={value.get('healthy', '-')}"
    )


@click.group("client")
def client_release() -> None:
    """Manage the versioned local FactorTester client distribution."""


client_release.add_command(client_adapter)
client_release.add_command(client_profile)


def _release_options(function):
    function = click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="Print machine-readable JSON.",
    )(function)
    function = click.option(
        "--dry-run",
        is_flag=True,
        help="Verify and print the mutation plan without writing.",
    )(function)
    return click.option(
        "--profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        required=True,
    )(function)


def _apply_release(
    profile: Path,
    *,
    dry_run: bool,
    as_json: bool,
) -> None:
    manifest, public_key, root = load_release_inputs(profile)
    store = ClientReleaseStore(root)
    plan = store.plan(manifest, public_key=public_key)
    if dry_run:
        _echo(plan, as_json)
        return
    receipt = store.install(manifest, public_key=public_key)
    _echo({
        "current_version": receipt["version"],
        "target_version": receipt["version"],
        "healthy": True,
        "receipt": receipt,
    }, as_json)


@client_release.command("bootstrap")
@_release_options
@friendly_errors
def bootstrap(profile: Path, dry_run: bool, as_json: bool) -> None:
    """Install idempotently from a signed release profile."""
    _apply_release(profile, dry_run=dry_run, as_json=as_json)


@client_release.command("update")
@_release_options
@friendly_errors
def update(profile: Path, dry_run: bool, as_json: bool) -> None:
    """Install and atomically select the profile's signed release."""
    _apply_release(profile, dry_run=dry_run, as_json=as_json)


@client_release.command("status")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def status(profile: Path | None, as_json: bool) -> None:
    """Read local receipts without network, database, or Agent calls."""
    _echo(ClientReleaseStore(load_profile_root(profile)).status(), as_json)


@client_release.command("rollback")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--to-version", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def rollback(
    profile: Path | None,
    to_version: str,
    as_json: bool,
) -> None:
    """Atomically select an already verified installed version."""
    result = ClientReleaseStore(
        load_profile_root(profile)
    ).rollback(to_version)
    _echo(result, as_json)
