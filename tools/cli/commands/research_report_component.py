"""Add structured components to a branch-owned Work Package report."""

from __future__ import annotations

from pathlib import Path
import hashlib

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import add_branch_component
from tools.cli.release.research_reporting.authoring import commit_branch_authoring
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_link_list,
)

from .research_report_common import component_content, output, rich_body, scope_options
from .research_report_scope import ensure_authoring, persist_descriptor, resolve_branch_report_scope


@click.command("add")
@scope_options
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "list", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option("--title", required=True)
@click.option(
    "--parent-id", default=None,
    help="父组件；除 chapter 外的组件必须指定",
)
@click.option(
    "--body", default=None,
    help="受限 Markdown 正文；可含公式、表格、代码及类型化 factortester:// 链接",
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
@click.option(
    "--item", "items", multiple=True,
    help="--kind list 的列表项；可重复使用",
)
@click.option(
    "--ordered/--unordered", default=False,
    help="--kind list 使用有序或无序标记",
)
@click.option(
    "--report-requirement-id", default="",
    help="当前组件满足的研究图报告要求；须与另外两个 report 选项一同使用",
)
@click.option(
    "--report-subject-ref", default="",
    help="报告要求对应的图对象引用；须与另外两个 report 选项一同使用",
)
@click.option(
    "--report-content-kind", default="",
    help="本组件用于覆盖该要求的内容类型；须与另外两个 report 选项一同使用",
)
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str | None, body_file: Path | None,
    display_kind: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str, items: tuple[str, ...], ordered: bool,
    report_requirement_id: str,
    report_subject_ref: str, report_content_kind: str, as_json: bool,
) -> None:
    """Add one structured component to the branch Work Package report.

    Use portable Markdown in --body/--body-file.  A typed inline reference is
    ``[说明](factortester://evidence/evidence%3Astable-ref)``; use its domain
    kind (evidence, obligation, task, job, artifact, and so on) as the host.
    The report only links to those objects and never registers them.
    """
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope, materialize=False)
    content = component_content(
        kind=kind, content_file=content_file, code_file=code_file,
        language=language, latex=latex, fallback=fallback,
        items=items, ordered=ordered,
    )
    report_binding, rendered_body = _report_requirement(
        component_id=component_id,
        body=rich_body(body=body, body_file=body_file),
        requirement_id=report_requirement_id,
        subject_ref=report_subject_ref,
        content_kind=report_content_kind,
    )
    saved = add_branch_component(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, component_id=component_id, kind=kind, title=title,
        parent_id=parent_id, body=rendered_body, content=content,
        display_kind=display_kind, bindings=[report_binding] if report_binding else None,
        materialize=False,
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


def _report_requirement(
    *, component_id: str, body: str, requirement_id: str, subject_ref: str,
    content_kind: str,
) -> tuple[dict[str, object] | None, str]:
    fields = (requirement_id, subject_ref, content_kind)
    if not any(fields):
        return None, body
    if not all(fields):
        raise click.ClickException(
            "--report-requirement-id, --report-subject-ref and "
            "--report-content-kind must be used together"
        )
    digest = hashlib.sha256(
        "\x1f".join((component_id, requirement_id, subject_ref)).encode()
    ).hexdigest()[:48]
    rendered = typed_link_list([{
        "kind": "report_requirement", "target_ref": requirement_id,
        "label": "报告义务",
    }])
    return ({
        "binding_id": f"report-requirement-{digest}",
        "kind": "report_requirement", "target_ref": requirement_id,
        "label": "报告义务",
        "data": {
            "report_requirement_id": requirement_id,
            "subject_ref": subject_ref,
            "content_kind": content_kind,
        },
    }, f"{body}\n\n关联：\n{rendered}".strip())
