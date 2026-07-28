"""Add structured components to a branch-owned Work Package report."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import add_branch_component
from tools.cli.release.research_reporting.authoring import commit_branch_authoring

from .research_report_common import component_content, output, rich_body, scope_options
from .research_report_scope import ensure_authoring, persist_descriptor, resolve_branch_report_scope


@click.command("add")
@scope_options
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option("--title", required=True)
@click.option(
    "--parent-id", default=None,
    help="父组件；除 chapter 外的组件必须指定",
)
@click.option(
    "--body", default=None,
    help="受限 Markdown 正文；可含行内/行间公式、表格和围栏代码",
)
@click.option(
    "--body-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="UTF-8 受限 Markdown 正文文件；不能与 --body 同用",
)
@click.option("--display-kind", default="")
@click.option(
    "--content-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="类型化组件的 JSON 内容（表格、结果、图像或特殊条目）",
)
@click.option(
    "--code-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="--kind code 的 UTF-8 源码文件",
)
@click.option("--language", default="text", show_default=True)
@click.option("--latex", default=None)
@click.option("--fallback", default="")
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str | None, body_file: Path | None,
    display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str, as_json: bool,
) -> None:
    """Add one structured component to the branch Work Package report."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope, materialize=False)
    saved = add_branch_component(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, component_id=component_id, kind=kind, title=title,
        parent_id=parent_id, body=rich_body(body=body, body_file=body_file),
        content=component_content(
            kind=kind, content_file=content_file, code_file=code_file,
            language=language, latex=latex, fallback=fallback,
        ), display_kind=display_kind, materialize=False,
    )
    persist_descriptor(scope, saved["descriptor"])
    git = commit_branch_authoring(
        scope.package_root, message="Add report component",
    )
    output({
        "component_id": component_id,
        "kind": kind, "body_format": "restricted_markdown",
        "generation": saved["head"]["generation"], "git": git,
    }, as_json)
