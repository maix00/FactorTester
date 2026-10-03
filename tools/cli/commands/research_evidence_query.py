"""Evidence guide, creation, inspection and search commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config

from .research_evidence_common import (
    emit,
    library_for_profile,
    profile_options,
    read_object,
)


def register_query_commands(group: click.Group) -> None:
    group.add_command(guide)
    group.add_command(create)
    group.add_command(get)
    group.add_command(list_catalog)
    group.add_command(search)
    group.add_command(facet)
    group.add_command(applicability)
    group.add_command(admit)
    group.add_command(exclude)
    group.add_command(restore)


@click.command("guide")
@click.argument(
    "topic",
    default="overview",
    type=click.Choice([
        "overview", "search", "capture", "fragment", "create", "tag", "bind",
    ]),
)
@click.option("--json", "as_json", is_flag=True)
def guide(topic: str, as_json: bool) -> None:
    """Return the current workflow contract instead of static Skill schema."""
    emit(_guide(topic), as_json)


@click.command("create")
@click.option(
    "--metadata-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@profile_options
@click.option("--json", "as_json", is_flag=True)
def create(
    metadata_file: Path,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().create_fragment_bound_evidence(
        read_object(metadata_file, "Evidence metadata")
    )
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    library.record_evidence(value)
    library.rebuild_index()
    emit({
        **value,
        "next_actions": [{
            "action": "search_or_bind",
            "argv": [
                "factortester", "research", "evidence", "search",
                "--json",
            ],
        }],
    }, as_json)


@click.command("get")
@click.argument("evidence_ref")
@click.option("--profile-id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def get(
    evidence_ref: str,
    profile_id: str | None,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().get_research_evidence(evidence_ref)
    if profile_id:
        library_for_profile(
            release_profile=release_profile, profile_id=profile_id,
        ).record_evidence(value)
    emit(value, as_json)


@click.command("search")
@click.option("--product-ref", multiple=True)
@click.option("--factor-ref", multiple=True)
@click.option("--sample-ref", multiple=True)
@click.option("--time-start")
@click.option("--time-end")
@click.option("--evidence-kind", multiple=True)
@click.option("--source-kind", multiple=True)
@click.option("--tag-ref", multiple=True)
@click.option("--text", default="")
@click.option("--limit", type=click.IntRange(1, 100), default=20)
@click.option(
    "--include-excluded",
    is_flag=True,
    help="审计时同时返回已排除 Evidence；默认检索不会发现它们",
)
@click.option("--json", "as_json", is_flag=True)
def search(
    product_ref: tuple[str, ...],
    factor_ref: tuple[str, ...],
    sample_ref: tuple[str, ...],
    time_start: str | None,
    time_end: str | None,
    evidence_kind: tuple[str, ...],
    source_kind: tuple[str, ...],
    tag_ref: tuple[str, ...],
    text: str,
    limit: int,
    include_excluded: bool,
    as_json: bool,
) -> None:
    if bool(time_start) != bool(time_end):
        raise click.ClickException(
            "--time-start and --time-end must be provided together"
        )
    query = {
        "product_ref": list(product_ref),
        "factor_ref": list(factor_ref),
        "sample_ref": list(sample_ref),
        "time_start": time_start,
        "time_end": time_end,
        "evidence_kind": list(evidence_kind),
        "source_kind": list(source_kind),
        "tag_ref": list(tag_ref),
        "text": text or None,
        "limit": limit,
        "include_excluded": "1" if include_excluded else None,
    }
    emit(client_from_config().search_research_evidence(query), as_json)


@click.command("list")
@click.option("--page", type=click.IntRange(min=1), default=1, show_default=True)
@click.option(
    "--page-size", type=click.IntRange(1, 100), default=20, show_default=True,
)
@click.option("--text", default="")
@click.option("--include-excluded", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def list_catalog(
    page: int,
    page_size: int,
    text: str,
    include_excluded: bool,
    as_json: bool,
) -> None:
    """List the metadata-only Evidence catalog one server page at a time."""
    emit(client_from_config().list_research_evidence_catalog({
        "page": page,
        "page_size": page_size,
        "text": text or None,
        "include_excluded": "1" if include_excluded else None,
    }), as_json)


@click.group("applicability")
def applicability() -> None:
    """Inspect or update the mutable interpretation scope of Evidence."""


@applicability.command("schema")
@click.option("--json", "as_json", is_flag=True)
def applicability_schema(as_json: bool) -> None:
    emit(client_from_config().get_research_evidence_applicability_schema(), as_json)


@applicability.command("show")
@click.argument("evidence_ref")
@click.option("--json", "as_json", is_flag=True)
def applicability_show(evidence_ref: str, as_json: bool) -> None:
    evidence = client_from_config().get_research_evidence(evidence_ref)
    emit({
        "evidence_ref": evidence.get("evidence_ref"),
        "applicability": evidence.get("applicability") or {},
    }, as_json)


@applicability.command("update")
@click.argument("evidence_ref")
@click.option(
    "--file", "applicability_file", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--json", "as_json", is_flag=True)
def applicability_update(
    evidence_ref: str, applicability_file: Path, as_json: bool,
) -> None:
    value = read_object(applicability_file, "Evidence applicability")
    evidence = client_from_config().update_research_evidence_applicability(
        evidence_ref, value,
    )
    emit({
        "evidence_ref": evidence.get("evidence_ref"),
        "applicability": evidence.get("applicability") or {},
    }, as_json)


@click.group("facet")
def facet() -> None:
    """Inspect immutable system facets and mutable Agent tags."""


@facet.command("list")
@click.option("--json", "as_json", is_flag=True)
def facet_list(as_json: bool) -> None:
    emit(client_from_config().list_research_evidence_facets(), as_json)


@click.command("admit")
@click.argument("evidence_ref")
@click.option("--environment-ref", required=True)
@click.option("--subject-ref", required=True)
@click.option(
    "--qualification",
    type=click.Choice(["unreviewed", "eligible", "limited", "rejected"]),
    required=True,
)
@click.option("--note", default="")
@click.option("--json", "as_json", is_flag=True)
def admit(
    evidence_ref: str,
    environment_ref: str,
    subject_ref: str,
    qualification: str,
    note: str,
    as_json: bool,
) -> None:
    value = client_from_config().admit_research_evidence(
        evidence_ref,
        environment_ref=environment_ref,
        subject_ref=subject_ref,
        qualification=qualification,
        note=note,
    )
    emit(value, as_json)


def _status_options(function):
    function = click.argument("evidence_ref")(function)
    function = click.option("--reason-zh", required=True)(function)
    function = click.option("--operation-id", required=True)(function)
    function = click.option("--json", "as_json", is_flag=True)(function)
    return function


@click.command("exclude")
@_status_options
def exclude(
    evidence_ref: str, reason_zh: str, operation_id: str, as_json: bool,
) -> None:
    """Exclude one owned Evidence object from ordinary discovery and reuse."""
    emit(client_from_config().change_research_evidence_status(
        evidence_ref,
        {"action": "exclude", "reason_zh": reason_zh,
         "operation_id": operation_id},
    ), as_json)


@click.command("restore")
@_status_options
def restore(
    evidence_ref: str, reason_zh: str, operation_id: str, as_json: bool,
) -> None:
    """Restore one excluded Evidence object without restoring old admissions."""
    emit(client_from_config().change_research_evidence_status(
        evidence_ref,
        {"action": "restore", "reason_zh": reason_zh,
         "operation_id": operation_id},
    ), as_json)


def _guide(topic: str) -> dict[str, Any]:
    """Describe the independent Evidence capture and qualification path."""
    steps = {
        "overview": [
            "按产品、因子版本和时间范围搜索已有 Evidence",
            "没有兼容结果时再捕获来源和精确片段",
            "按明确的研究主体与环境记录资格和理由",
        ],
        "search": [
            "先使用结构化 scope，再使用系统 Facet 和 Agent Tag",
            "因子集合使用完整冻结记录对应的 factor-set:v2 target_ref",
        ],
        "capture": [
            "优先复用外部 Web 链接、权威 API、Terminal 或 Job 来源",
            "一个来源可以创建多个片段，不得直接充当 Evidence",
            "Agent 自写报告和手工复制输出不得作为原始来源",
            "本地文件仅接受带权威下载链路或 Git commit/blob provenance 的来源",
            "下载脚本和请求参数只证明获取链路，不能代替原始内容",
        ],
        "fragment": ["选择精确字段、行、生成物或时间点并冻结内容哈希"],
        "create": [
            "Evidence 必须引用至少一个精确 fragment_ref",
            "Evidence 陈述不得超过来源片段能证明的范围",
        ],
        "tag": ["先 propose；仅在现有标签不适用时 create"],
        "bind": ["用 evidence admit 对主体与环境记录资格"],
    }[topic]
    next_action = {
        "overview": ["factortester", "research", "evidence", "guide", "search", "--json"],
        "search": ["factortester", "research", "evidence", "search", "--json"],
        "capture": ["factortester", "research", "evidence", "source", "--help"],
        "fragment": ["factortester", "research", "evidence", "fragment", "add", "--help"],
        "create": ["factortester", "research", "evidence", "create", "--help"],
        "tag": ["factortester", "research", "evidence", "tag", "list", "--json"],
        "bind": ["factortester", "research", "evidence", "admit", "--help"],
    }[topic]
    return {
        "topic": topic,
        "rules": steps,
        "next_actions": [{"action": topic, "argv": next_action}],
    }
