"""Add structured components to a branch-owned Work Package report."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root

from .research_report_common import output, scope_options
from .research_report_component_write import write_report_component


@click.command("add")
@scope_options
@click.option("--component-id", required=True)
@click.option("--kind", type=click.Choice([
    "chapter", "section", "subsection", "entry", "special", "list", "table",
    "image", "code", "math", "result",
]), required=True)
@click.option(
    "--title", default="",
    help=(
        "结构节点 chapter/section/special 必须提供真实标题；section 可递归嵌套，subsection 是 section 的兼容别名；特殊小节与普通节的层级均由父子关系决定；"
        "章节直属内容部件必须省略标题；可折叠内容应先创建 section"
    ),
)
@click.option(
    "--parent-id", default=None,
    help=(
        "父组件；省略时使用 --target-chapter-id 或报告树最后一个章节"
    ),
)
@click.option(
    "--target-chapter-id", default="",
    help=(
        "明确写入的章节组件 ID；省略时使用报告树最后一个章节，补写旧要求时"
        "必须使用 CLI 返回的来源章节 ID"
    ),
)
@click.option(
    "--before-component-id", default=None,
    help="将新条目插入同一父容器中指定组件的正上方",
)
@click.option(
    "--after-component-id", default=None,
    help="将新条目插入同一父容器中指定组件的正下方",
)
@click.option(
    "--body", default=None,
    help="受限 Markdown 正文；可含公式、表格、代码及类型化 factortester:// 链接",
)
@click.option(
    "--body-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="UTF-8 受限 Markdown 正文文件；不能与 --body 同用",
)
@click.option(
    "--display-kind", default="",
    help=(
        "特殊小节语义；Agent 可用 grill_resolution、external_review "
        "或 obligation_requirement"
    ),
)
@click.option(
    "--obligation-requirement-id", default="",
    help=(
        "义务小类 ID；与 --kind special 和 "
        "--display-kind obligation_requirement 一同使用"
    ),
)
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
@click.option(
    "--submission-sequence", type=click.IntRange(min=1), default=None,
    help="修正被拦截的提交时必须复用 CLI 返回的提交序号",
)
@click.option(
    "--owner-chapter-authorization", type=int, default=None, hidden=True,
)
@click.option("--json", "as_json", is_flag=True)
def add_report_component(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, kind: str, title: str,
    parent_id: str | None, body: str | None, body_file: Path | None,
    target_chapter_id: str, before_component_id: str | None,
    after_component_id: str | None,
    display_kind: str, obligation_requirement_id: str,
    content_file: Path | None, code_file: Path | None, language: str,
    latex: str | None, fallback: str, items: tuple[str, ...], ordered: bool,
    report_requirement_id: str,
    report_subject_ref: str, report_content_kind: str,
    submission_sequence: int | None,
    owner_chapter_authorization: int | None,
    as_json: bool,
) -> None:
    """Add one structured component to the branch Work Package report.

    Use portable Markdown in --body/--body-file.  A typed inline reference is
    ``[说明](factortester://evidence/evidence%3Astable-ref)``; use its domain
    kind (evidence, obligation, task, job, artifact, and so on) as the host.
    The report only links to those objects and never registers them.
    """
    if before_component_id is not None and after_component_id is not None:
        raise click.UsageError(
            "--before-component-id and --after-component-id are mutually exclusive"
        )
    result = write_report_component(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id, work_package_id=work_package_id,
        branch_id=branch_id, component_id=component_id, kind=kind,
        title=title, parent_id=parent_id, body=body, body_file=body_file,
        target_chapter_id=target_chapter_id,
        before_component_id=before_component_id,
        after_component_id=after_component_id,
        display_kind=display_kind, content_file=content_file,
        code_file=code_file, language=language, latex=latex,
        fallback=fallback, items=items, ordered=ordered,
        obligation_requirement_id=obligation_requirement_id,
        requirement_id=report_requirement_id, subject_ref=report_subject_ref,
        content_kind=report_content_kind,
        submission_sequence=submission_sequence, as_json=as_json,
        owner_chapter_authorization=owner_chapter_authorization,
    )
    output(result, as_json)
