"""Add structured components to a branch-owned Work Package report."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import add_branch_component
from tools.cli.release.research_reporting.writer import render_branch_authoring_report

from .research_report_common import component_content, output, scope_options
from .research_report_scope import ensure_authoring, persist_descriptor, resolve_branch_report_scope


@click.command("add")
@scope_options
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option("--title", required=True)
@click.option("--parent-id", default=None)
@click.option("--body", default="")
@click.option("--display-kind", default="")
@click.option("--content-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--code-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--language", default="text", show_default=True)
@click.option("--latex", default=None)
@click.option("--fallback", default="")
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str, display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str, as_json: bool,
) -> None:
    """Add one structured component to the branch Work Package report."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope)
    saved = add_branch_component(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, component_id=component_id, kind=kind, title=title,
        parent_id=parent_id, body=body,
        content=component_content(
            kind=kind, content_file=content_file, code_file=code_file,
            language=language, latex=latex, fallback=fallback,
        ), display_kind=display_kind,
    )
    persist_descriptor(scope, saved["descriptor"])
    rendered = render_branch_authoring_report(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id,
    )
    output({
        "component_id": component_id,
        "revision": saved["head"]["revision"], "git": rendered["git"],
    }, as_json)
