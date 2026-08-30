"""Public deterministic client install, update, status, and rollback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from urllib.error import URLError

import click

from tools.cli.commands.client_adapter import client_adapter
from tools.cli.commands.client_catalog import (
    catalog_factor,
    catalog_factor_set,
    catalog_family,
    catalog_local_run,
    catalog_migration,
    catalog_owner,
    catalog_revision,
    catalog_source,
    catalog_status,
    init_catalog,
)
from tools.cli.commands.client_profile import client_profile, profile_factor_worktree
from tools.cli.modules.custom_factors.factor_library import factor_library
from tools.cli.commands.client_profile_factor_reference import (
    register_factor_reference_commands,
)
from tools.cli.commands.client_profile_factor_set import (
    register_factor_set_commands,
)
from tools.cli.commands.client_profile_revision import (
    register_profile_revision_commands,
)
from tools.cli.commands.strategy_profile import register_strategy_profile_commands
from tools.cli.core.errors import friendly_errors
from tools.cli.local_sources import default_local_sources_root
from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import (
    ManagerConfig,
    ManagerCredentialStore,
)
from tools.cli.release.app_update_control import dispatch_app_update, read_status
from tools.cli.release.bundle_runtime import activate_bundled_runtime
from tools.cli.release.client_release_bundle import inspect_client_release_bundle
from tools.cli.release.locations import default_client_root, validate_client_root
from tools.cli.release.profile import (
    load_profile_root,
    load_release_inputs,
)
from tools.cli.release.transaction import ClientReleaseStore


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


def _release_source_root() -> Path | None:
    for source_root in (Path.cwd(), Path(__file__).resolve().parents[3]):
        if (source_root / "scripts" / "release" / "publish.py").is_file():
            return source_root
    return None


def _run_release_with_host_python(
    source_root: Path,
    options: dict,
) -> None:
    interpreter = os.environ.get("FTCLIENT_RELEASE_PYTHON") or shutil.which(
        "python3"
    )
    if not interpreter:
        raise click.ClickException(
            "A host python3 interpreter is required to publish a client release"
        )
    command = [
        interpreter,
        str(source_root / "scripts" / "release" / "publish.py"),
    ]
    for name, value in options.items():
        if value is None or value is False:
            continue
        flag = f"--{name.replace('_', '-')}"
        command.append(flag)
        if value is not True:
            command.append(str(value))
    environment = os.environ.copy()
    environment.pop("FACTORTESTER_ENTRYPOINT", None)
    subprocess.run(
        command,
        cwd=source_root,
        env=environment,
        check=True,
    )


client.add_command(client_adapter)
client.add_command(client_profile)
client.add_command(catalog_source, name="source")
client.add_command(catalog_local_run, name="local-run")
client.add_command(catalog_migration, name="migration")
register_strategy_profile_commands(client_profile)
register_profile_revision_commands(client_profile)
register_factor_reference_commands(profile_factor_worktree)
register_factor_set_commands(profile_factor_worktree)
factor_library.add_command(profile_factor_worktree, name="profile")
profile_factor_worktree.add_command(catalog_owner, name="owners")
profile_factor_worktree.add_command(catalog_revision, name="revisions")
profile_factor_worktree.add_command(catalog_family, name="families")
profile_factor_worktree.add_command(catalog_factor, name="factors")
profile_factor_worktree.add_command(catalog_factor_set, name="factor-sets")


@client.group("storage", hidden=True)
def client_storage() -> None:
    """Maintain the native client's embedded storage."""


client_storage.add_command(init_catalog, name="init")
client_storage.add_command(catalog_status, name="status")


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
@click.option(
    "--server-ca-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="CA/certificate used to verify the Beta Manager during discovery.",
)
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
    source_root = _release_source_root()
    if source_root is None:
        raise click.ClickException(
            "Run client release from a FactorTester source checkout"
        )
    from tools.cli.release.signing_keys import manifest_private_key

    options["legacy_private_key"] = manifest_private_key(
        str(options.get("channel") or ""),
        options.get("legacy_private_key"),
    )
    if getattr(sys, "frozen", False):
        _run_release_with_host_python(source_root, options)
        return
    if source_root is not None:
        source_root_text = str(source_root)
        if source_root_text not in sys.path:
            sys.path.insert(0, source_root_text)
    from scripts.release.publish import publish_release as run_release
    receipt = run_release(**options)
    click.echo(json.dumps(receipt.__dict__, ensure_ascii=False, indent=2))


@operator_client.command("release-upload")
@click.option(
    "--target",
    "targets",
    multiple=True,
    required=True,
    help="目标 Manager 的 HTTP(S) 地址；可重复指定多个在线服务器。",
)
@click.option(
    "--package",
    "package_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="已经生成的单目标 ZIP 包；多目标发布请使用 --release-dir。",
)
@click.option(
    "--release-dir",
    "release_directory",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="factortester-manager client release 的输出目录；按目标重签名并打包。",
)
@click.option("--version", default="", help="可选；默认读取包内 beta.json。")
@click.option("--build", type=click.IntRange(min=1), default=None)
@click.option(
    "--legacy-private-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="目标 URL 重签 Beta manifest 时使用的私钥。",
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def upload_release(
    targets: tuple[str, ...],
    package_path: Path | None,
    release_directory: Path | None,
    version: str,
    build: int | None,
    legacy_private_key: Path | None,
    as_json: bool,
) -> None:
    """Upload one already-built signed Beta package to each target Manager.

    The package is sent through the Manager-issued 7997 capability.  An
    unreachable target is reported and skipped once; it is never retried or
    republished implicitly.
    """
    if bool(package_path) == bool(release_directory):
        raise click.ClickException("必须且只能指定 --package 或 --release-dir")
    if package_path is not None and len(targets) > 1:
        raise click.ClickException(
            "向多个目标发布时必须使用 --release-dir，以便为每个 URL 重签 manifest"
        )
    if release_directory is not None:
        # Retargeting a release is an operator-only path.  Keep its publisher
        # helpers out of the regular client import graph so the bundled wheel
        # runs outside the source checkout without the server-side scripts
        # package.
        from tools.cli.release.client_release_targets import (
            build_target_beta_package,
        )
    trusted_public_key = Path(str(
        files("tools.cli.release").joinpath("trusted-beta-release-public.pem")
    ))
    private_key = None
    if release_directory is not None:
        from tools.cli.release.signing_keys import manifest_private_key

        private_key = manifest_private_key("beta", legacy_private_key)
    selected_version = str(version or "").strip()
    selected_build = int(build or 0)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="factortester-release-upload-") as raw:
        staging = Path(raw)
        for index, target in enumerate(targets):
            package_for_target = package_path
            metadata: dict[str, object]
            try:
                config = ManagerConfig.from_url(target)
                if release_directory is not None:
                    package_for_target = staging / f"target-{index}.zip"
                    metadata = build_target_beta_package(
                        release_directory,
                        target_origin=config.base_url,
                        output=package_for_target,
                        private_key=private_key,  # type: ignore[arg-type]
                        public_key=trusted_public_key,
                    )
                else:
                    metadata = inspect_client_release_bundle(package_for_target)  # type: ignore[arg-type]
                selected_version = selected_version or str(metadata["version"])
                selected_build = selected_build or int(metadata["build"])
                if selected_version != str(metadata["version"]):
                    raise click.ClickException("版本与 Beta 包内版本不一致")
                if selected_build != int(metadata["build"]):
                    raise click.ClickException("构建号与 Beta 包内构建号不一致")
                token = ManagerCredentialStore(config).read()
                if not token:
                    results.append({
                        "target": config.base_url,
                        "status": "not_configured",
                        "error": "没有该目标 Manager 的 Keychain 会话",
                    })
                    continue
                client = ManagerClient(config, token=token, timeout=30)
                client.require_manager()
                receipt = client.upload_client_beta_release(
                    package_for_target,  # type: ignore[arg-type]
                    version=selected_version,
                    build=selected_build,
                    timeout=15 * 60,
                )
                results.append({"target": config.base_url, "status": "published", **receipt})
            except Exception as exc:  # target isolation is deliberate
                if _release_target_offline(exc):
                    results.append({
                        "target": str(target).rstrip("/"),
                        "status": "offline",
                        "error": "目标 Manager 不在线；本次跳过，稍后可手动补发",
                    })
                    continue
                raise
    published_digests = {
        str(item["package_sha256"])
        for item in results
        if item.get("status") == "published" and item.get("package_sha256")
    }
    payload = {
        "success": any(item.get("status") == "published" for item in results),
        "channel": "beta",
        "version": selected_version,
        "build": selected_build,
        # Per-target packages are intentionally different because their
        # signed URLs contain different Manager origins.  Keep a scalar only
        # when it is unambiguous; target receipts always retain their digest.
        "package_sha256": next(iter(published_digests))
        if len(published_digests) == 1 else None,
        "targets": results,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in results:
            click.echo(
                f"{item.get('target')}: {item.get('status')}"
                + (f" ({item.get('error')})" if item.get("error") else "")
            )


def _release_target_offline(error: BaseException) -> bool:
    from tools.cli.http import HttpClientError

    if isinstance(error, (ConnectionError, TimeoutError, URLError)):
        return True
    return isinstance(error, HttpClientError) and (
        error.status == 0 or error.status in {408, 425, 429} or error.status >= 500
    )


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
