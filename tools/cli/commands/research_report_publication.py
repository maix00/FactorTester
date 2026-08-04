"""Publish or revoke one live, source-free research-report projection."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.public_research import (
    PublicResearchLibrary,
)

from .research_report_common import output, scope_options


@click.group("publication")
def publication() -> None:
    """Manage explicit public visibility; local report updates stay live."""


@publication.command("list")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def list_publications(release_profile: Path | None, as_json: bool) -> None:
    library = PublicResearchLibrary(load_profile_root(release_profile))
    output({"publications": library.list_publications()}, as_json)


@publication.command("local")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def list_local(release_profile: Path | None, as_json: bool) -> None:
    library = PublicResearchLibrary(load_profile_root(release_profile))
    output({"reports": library.list_local_reports()}, as_json)


@publication.command("publish")
@scope_options
@click.option("--title", default="", help="可选的公开标题")
@click.option("--show-profile", is_flag=True, help="在公开页面显示 Profile 名称")
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
    confirm_public: bool,
    as_json: bool,
) -> None:
    """Make one local branch report continuously visible on Manager 7998."""
    if not confirm_public:
        raise click.ClickException(
            "public confirmation is required; preview the report, then pass "
            "--confirm-public"
        )
    library = PublicResearchLibrary(load_profile_root(release_profile))
    value = library.publish(
        profile_id=profile_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
        public_title=title,
        show_profile=show_profile,
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
    """Immediately revoke one public report URL and list entry."""
    library = PublicResearchLibrary(load_profile_root(release_profile))
    output(library.unpublish(publication_id), as_json)
