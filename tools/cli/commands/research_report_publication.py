"""Publish or revoke one live, source-free research-report projection."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.public_research import (
    PublicResearchClient,
)

from .research_report_common import output, scope_options


@click.group("publication")
def publication() -> None:
    """Manage explicit sharing; authoring remains local-first."""


@publication.command("sync")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def sync_publications(release_profile: Path | None, as_json: bool) -> None:
    """Flush shared-report changes accumulated while offline."""
    library = PublicResearchClient(load_profile_root(release_profile))
    output({"operations": library.sync_pending()}, as_json)


@publication.command("list")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def list_publications(release_profile: Path | None, as_json: bool) -> None:
    library = PublicResearchClient(load_profile_root(release_profile))
    output({"publications": library.list_publications()}, as_json)


@publication.command("local")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def list_local(release_profile: Path | None, as_json: bool) -> None:
    library = PublicResearchClient(load_profile_root(release_profile))
    output({"reports": library.list_local_reports()}, as_json)


@publication.command("publish")
@scope_options
@click.option("--title", default="", help="可选的公开标题")
@click.option("--show-profile", is_flag=True, help="在公开页面显示 Profile 名称")
@click.option(
    "--visibility", type=click.Choice(["authorized", "public"]),
    default="public", show_default=True,
)
@click.option("--authorized-user", "authorized_users", multiple=True)
@click.option(
    "--confirm-public",
    is_flag=True,
    help="确认任何持有链接的人都可阅读当前及后续报告内容",
)
@click.option("--json", "as_json", is_flag=True)
def publish_report(
    profile_id: str,
    work_package_id: str,
    branch_id: str,
    release_profile: Path | None,
    title: str,
    show_profile: bool,
    visibility: str,
    authorized_users: tuple[str, ...],
    confirm_public: bool,
    as_json: bool,
) -> None:
    """Share one local branch report, or queue it until Manager is reachable."""
    if visibility == "public" and not confirm_public:
        raise click.ClickException(
            "public confirmation is required; preview the report, then pass "
            "--confirm-public"
        )
    library = PublicResearchClient(load_profile_root(release_profile))
    value = library.publish(
        profile_id=profile_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        public_title=title,
        show_profile=show_profile,
        visibility=visibility,
        authorized_users=authorized_users,
    )
    output(value, as_json)


@publication.command("unpublish")
@click.argument("publication_id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def unpublish_report(
    publication_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    """Revoke a shared report now or queue the revocation while offline."""
    library = PublicResearchClient(load_profile_root(release_profile))
    output(library.unpublish(publication_id), as_json)


@publication.command("settings")
@click.argument("publication_id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--visibility", type=click.Choice(["private", "authorized", "public"]),
    required=True,
)
@click.option("--auto-upload/--no-auto-upload", default=True, show_default=True)
@click.option("--relay-local-files/--no-relay-local-files", default=False)
@click.option("--authorized-user", "authorized_users", multiple=True)
@click.option("--confirm-public", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def configure_publication(
    publication_id: str,
    release_profile: Path | None,
    visibility: str,
    auto_upload: bool,
    relay_local_files: bool,
    authorized_users: tuple[str, ...],
    confirm_public: bool,
    as_json: bool,
) -> None:
    """Configure visibility and automatic upload for one uploaded Branch."""
    if visibility == "public" and not confirm_public:
        raise click.ClickException(
            "public confirmation is required; pass --confirm-public"
        )
    library = PublicResearchClient(load_profile_root(release_profile))
    output(library.configure(
        publication_id,
        visibility=visibility,
        auto_sync=auto_upload,
        relay_local_files=relay_local_files,
        authorized_users=authorized_users,
    ), as_json)
