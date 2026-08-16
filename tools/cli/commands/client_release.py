"""Public deterministic client install, update, status, and rollback."""

from __future__ import annotations

import json
from pathlib import Path
import sys

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
from tools.cli.release.app_update_control import dispatch_app_update, read_status
from tools.cli.commands.client_adapter import client_adapter
from tools.cli.commands.client_catalog import client_catalog
from tools.cli.commands.client_profile import client_profile, profile_factor_worktree
from tools.cli.commands.client_profile_factor_reference import (
    register_factor_reference_commands,
)
from tools.cli.commands.client_profile_factor_set import (
    register_factor_set_commands,
)
from tools.cli.commands.client_profile_revision import (
    register_profile_revision_commands,
)
from tools.cli.commands.client_research import client_research
from tools.cli.commands.strategy_profile import register_strategy_profile_commands
from tools.cli.local_sources import default_local_sources_root


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
def client() -> None:
    """Manage the versioned local FactorTester client distribution."""


@click.group("client")
def operator_client() -> None:
    """Manage authorized FactorTester client publication."""


client.add_command(client_adapter)
client.add_command(client_catalog)
client.add_command(client_profile)
client.add_command(client_research)
register_strategy_profile_commands(client_profile)
register_profile_revision_commands(client_profile)
register_factor_reference_commands(profile_factor_worktree)
register_factor_set_commands(profile_factor_worktree)


@client.group("app-update")
def app_update() -> None:
    """Control FTClient's single Sparkle application updater."""


@app_update.command("check")
@click.option("--json", "as_json", is_flag=True)
@click.option("--wait", type=click.FloatRange(min=0), default=0, show_default=True)
@friendly_errors
def app_update_check(as_json: bool, wait: float) -> None:
    """Ask FTClient/Sparkle to check its selected channel."""
    _echo(dispatch_app_update("check", wait=wait), as_json)


@app_update.command("download")
@click.option("--json", "as_json", is_flag=True)
@click.option("--wait", type=click.FloatRange(min=0), default=0, show_default=True)
@friendly_errors
def app_update_download(as_json: bool, wait: float) -> None:
    """Ask FTClient/Sparkle to download and prepare its available update."""
    _echo(dispatch_app_update("download", wait=wait), as_json)


@app_update.command("status")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def app_update_status(as_json: bool) -> None:
    """Read the last update state written by FTClient."""
    value = read_status()
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"state={value.get('state', 'unknown')} "
        f"installed={value.get('installed_version', '-')} "
        f"latest={value.get('latest_version', '-')}"
    )


@app_update.command("restart")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def app_update_restart(as_json: bool) -> None:
    """Ask Sparkle to install the prepared update and relaunch FTClient."""
    _echo(dispatch_app_update("restart"), as_json)


@operator_client.command("release")
@click.option("--channel", type=click.Choice(["stable", "beta"]), required=True)
@click.option(
    "--version",
    default="auto",
    show_default=True,
    help="Beta: auto-increment from reachable Beta manifests; Stable: required.",
)
@click.option(
    "--build",
    default="auto",
    show_default=True,
    help="Beta: next build above reachable servers; Stable: required.",
)
@click.option("--source-revision", required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option(
    "--signing-identity",
    default="FTClient Beta Release",
    show_default=True,
)
@click.option("--sparkle-public-key", required=True)
@click.option(
    "--sparkle-generate-appcast",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option(
    "--legacy-private-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Manifest signing key; Beta defaults to the persistent FactorTester "
        "server release key."
    ),
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
@click.option(
    "--delta-only",
    is_flag=True,
    help="Beta-only: publish only the delta from the previous version.",
)
@click.option(
    "--previous-archive",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Previous app archive used to create a Sparkle delta.",
)
@click.option(
    "--previous-appcast",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Previous appcast to update when creating a Sparkle delta.",
)
@click.option(
    "--from-clean-commit",
    help=(
        "Explicitly build from this clean commit in a temporary worktree; "
        "must equal --source-revision."
    ),
)
@friendly_errors
def publish_release(**options) -> None:
    """Build, sign, notarize, publish, and read back Main or Beta."""
    # Release authoring lives beside the source checkout rather than inside
    # the public client package.  The editable CLI entrypoint still needs to
    # resolve that namespace when launched from Conda (console scripts do not
    # add the current working directory to ``sys.path``).
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "script" / "release" / "publish.py").is_file():
        source_root_text = str(source_root)
        if source_root_text not in sys.path:
            sys.path.insert(0, source_root_text)
    from scripts.release.publish import publish_release as run_release
    from tools.cli.release.signing_keys import manifest_private_key

    options["legacy_private_key"] = manifest_private_key(
        str(options.get("channel") or ""),
        options.get("legacy_private_key"),
    )
    receipt = run_release(**options)
    click.echo(json.dumps(receipt.__dict__, ensure_ascii=False, indent=2))


@client.command("activate-bundle", hidden=True)
@click.option(
    "--bundle-resources",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--client-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--local-skill-root",
    type=click.Path(file_okay=False, path_type=Path),
    hidden=True,
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def activate_bundle(
    bundle_resources: Path,
    client_root: Path | None,
    local_skill_root: Path | None,
    as_json: bool,
) -> None:
    """Activate the verified offline runtime embedded in FTClient."""
    result = activate_bundled_runtime(
        bundle_resources,
        validate_client_root(client_root)
        if client_root is not None
        else default_client_root(),
        local_skill_root=(
            local_skill_root
            if local_skill_root is not None
            else Path.home() / ".agents" / "skills"
        ),
        local_source_root=default_local_sources_root(),
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


@client.command("bootstrap")
@_release_options
@friendly_errors
def bootstrap(profile: Path, dry_run: bool, as_json: bool) -> None:
    """Install idempotently from a signed release profile."""
    _apply_release(profile, dry_run=dry_run, as_json=as_json)


@client.command("update")
@_release_options
@friendly_errors
def update(profile: Path, dry_run: bool, as_json: bool) -> None:
    """Install and atomically select the profile's signed release."""
    _apply_release(profile, dry_run=dry_run, as_json=as_json)


@client.command("status")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def status(profile: Path | None, as_json: bool) -> None:
    """Read local receipts without network, database, or Agent calls."""
    _echo(ClientReleaseStore(load_profile_root(profile)).status(), as_json)


@client.command("check-update")
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


@client.command("update-app")
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def update_app(profile: Path, as_json: bool) -> None:
    """Compatibility alias: ask FTClient/Sparkle to download the update."""
    _echo(dispatch_app_update("download"), as_json)


@client.command("rollback")
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
