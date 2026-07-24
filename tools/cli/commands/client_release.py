"""Public deterministic client install, update, status, and rollback."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import (
    load_profile_root,
    load_release_inputs,
    load_update_inputs,
)
from tools.cli.release.transaction import ClientReleaseStore
from tools.cli.release.bundle_runtime import activate_bundled_runtime
from tools.cli.release.locations import default_client_root, validate_client_root
from tools.cli.release.app_update import update_application
from tools.cli.commands.client_adapter import client_adapter
from tools.cli.commands.client_profile import client_profile
from tools.cli.commands.client_research import client_research


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
client_release.add_command(client_research)


@client_release.command("release")
@click.option("--channel", type=click.Choice(["stable", "beta"]), required=True)
@click.option("--version", required=True)
@click.option("--build", type=click.IntRange(min=1), required=True)
@click.option("--source-revision", required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--signing-identity", required=True)
@click.option("--sparkle-public-key", required=True)
@click.option(
    "--sparkle-generate-appcast",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--legacy-private-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--legacy-public-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--server-origin")
@click.option("--release-root", type=click.Path(path_type=Path))
@click.option(
    "--github-repository",
    default="maix00/FactorTester-Client",
    show_default=True,
)
@click.option("--cache-dir", type=click.Path(path_type=Path))
@click.option("--minimum-client", default="0.1.0", show_default=True)
@click.option("--mandatory", is_flag=True)
@click.option("--notary-profile")
@friendly_errors
def publish_release(**options) -> None:
    """Build, sign, notarize, publish, and read back Main or Beta."""
    from script.release.publish import release_client

    receipt = release_client(**options)
    click.echo(json.dumps(receipt.__dict__, ensure_ascii=False, indent=2))


@client_release.command("activate-bundle", hidden=True)
@click.option(
    "--bundle-resources",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--client-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def activate_bundle(
    bundle_resources: Path,
    client_root: Path | None,
    as_json: bool,
) -> None:
    """Activate the verified offline runtime embedded in FTClient."""
    result = activate_bundled_runtime(
        bundle_resources,
        validate_client_root(client_root)
        if client_root is not None
        else default_client_root(),
    )
    _echo(result, as_json)


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


@client_release.command("check-update")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def check_update(profile: Path, as_json: bool) -> None:
    """Read trusted server-first stable/beta update metadata."""
    _, update, source = load_update_inputs(profile)
    value = {
        "schema_version": 1,
        "source": source,
        "version": update.version,
        "build": update.build,
        "channel": update.channel,
        "dmg_url": update.dmg_url,
        "sha256": update.dmg_sha256,
        "minimum_client": update.minimum_client,
        "mandatory": update.mandatory,
        "published_at": update.published_at,
        "manifest_hash": update.manifest_hash,
        "signature_verified": True,
    }
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"version={update.version} build={update.build} "
        f"channel={update.channel} source={source} signature=verified"
    )


@client_release.command("update-app")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def update_app(profile: Path, as_json: bool) -> None:
    """Download, verify, atomically replace, and launch FTClient.app."""
    _, update, _ = load_update_inputs(profile)
    support = (
        Path.home() / "Library/Application Support/FactorTester"
    )
    _echo(
        update_application(
            update,
            application=Path("/Applications/FTClient.app"),
            support_root=support,
        ),
        as_json,
    )


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
