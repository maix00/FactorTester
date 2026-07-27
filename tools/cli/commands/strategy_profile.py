"""Profile CLI commands for the independent strategy Actor worktree."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.strategy_workspace import (
    CanonicalStrategyRepoStore,
    initialize_strategy_repo,
)
from tools.cli.release.strategy_worktree import (
    apply_strategy_worktree_binding,
    plan_strategy_worktree_binding,
)
from tools.cli.release.strategy_worktree_audit import (
    rollback_strategy_worktree_binding,
    verify_strategy_worktree_binding,
)
from tools.cli.release.user_layout import default_user_strategy_library
from tools.cli.release.storage import read_json, write_json


def register_strategy_profile_commands(profile_group) -> None:
    group = click.Group("strategy-worktree", help="管理独立 Strategy Actor 源码工作区。")
    profile_group.add_command(group)

    @group.command("canonical-register")
    @click.option("--path", type=click.Path(file_okay=False, path_type=Path))
    @click.option("--owner-ref", required=True)
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def canonical_register(path: Path | None, owner_ref: str, release_profile: Path | None) -> None:
        target = (path or default_user_strategy_library(owner_ref)).expanduser().resolve()
        initialize_strategy_repo(target, owner_ref=owner_ref)
        click.echo(_json(CanonicalStrategyRepoStore(load_profile_root(release_profile)).register(target, owner_ref=owner_ref)))

    @group.command("canonical-show")
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def canonical_show(release_profile: Path | None) -> None:
        click.echo(_json(CanonicalStrategyRepoStore(load_profile_root(release_profile)).load()))

    @group.command("plan")
    @click.argument("profile_id")
    @click.option("--branch", default="")
    @click.option("--source-sync/--no-source-sync", default=False)
    @click.option("--output", required=True, type=click.Path(dir_okay=False, path_type=Path))
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def plan(profile_id: str, branch: str, source_sync: bool, output: Path, release_profile: Path | None) -> None:
        value = plan_strategy_worktree_binding(load_profile_root(release_profile), profile_id, branch=branch, source_sync_enabled=source_sync)
        write_json(output, value)
        click.echo(_json(value))

    @group.command("apply")
    @click.argument("plan_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def apply(plan_path: Path, release_profile: Path | None) -> None:
        value = read_json(plan_path)
        if not isinstance(value, dict):
            raise click.ClickException("strategy worktree plan must be an object")
        click.echo(_json(apply_strategy_worktree_binding(load_profile_root(release_profile), value)))

    @group.command("verify")
    @click.argument("profile_id")
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def verify(profile_id: str, release_profile: Path | None) -> None:
        click.echo(_json(verify_strategy_worktree_binding(load_profile_root(release_profile), profile_id)))

    @group.command("rollback")
    @click.argument("profile_id")
    @click.option("--release-profile", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def rollback(profile_id: str, release_profile: Path | None) -> None:
        click.echo(_json(rollback_strategy_worktree_binding(load_profile_root(release_profile), profile_id)))


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
