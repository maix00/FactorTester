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
from .research_graph_cycle_contract import (
    validate_research_cycle_envelope,
)
from .research_graph_obligations import (
    record_evidence_lifecycle_report,
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
    group.add_command(admit_graph)
    group.add_command(exclude)
    group.add_command(restore)


@click.command("guide")
@click.argument(
    "topic",
    default="overview",
    type=click.Choice([
        "overview", "search", "capture", "fragment", "create", "tag", "bind",
        "exclude",
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


def _lifecycle_command():
    def decorator(function):
        function = click.argument("branch_id")(function)
        function = click.argument("instance_id")(function)
        function = click.argument("evidence_ref")(function)
        function = click.option("--profile-id", required=True)(function)
        function = click.option("--agent-id", required=True)(function)
        function = click.option("--parent-id", required=True)(function)
        function = click.option(
            "--reason-zh",
            required=True,
            help="写入生命周期事件和报告的简短中文裁决理由",
        )(function)
        function = click.option(
            "--change-file",
            required=True,
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="Research Cycle、必要义务变化及富文本解释",
        )(function)
        function = click.option(
            "--submission-sequence",
            type=click.IntRange(min=1),
            default=None,
        )(function)
        function = click.option(
            "--release-profile",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
        )(function)
        function = click.option("--json", "as_json", is_flag=True)(function)
        return function
    return decorator


@click.command("exclude")
@_lifecycle_command()
def exclude(**kwargs) -> None:
    """排除 Evidence、解除本分支覆盖并自动写入研究报告。"""
    _change_lifecycle(action="exclude", **kwargs)


@click.command("restore")
@_lifecycle_command()
def restore(**kwargs) -> None:
    """恢复 Evidence 的可发现资格；不会恢复旧 EvidenceUse。"""
    _change_lifecycle(action="restore", **kwargs)


def _change_lifecycle(
    *,
    action: str,
    evidence_ref: str,
    instance_id: str,
    branch_id: str,
    profile_id: str,
    agent_id: str,
    parent_id: str,
    reason_zh: str,
    change_file: Path,
    submission_sequence: int | None,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    change_payload = _read_lifecycle_change(change_file)
    client = client_from_config()
    evidence = client.get_research_evidence(evidence_ref)
    transition = client.prepare_research_evidence_lifecycle(
        evidence_ref,
        {
            "action": action,
            "reason_zh": reason_zh,
            "profile_ref": f"profile:{profile_id}",
            "agent_id": agent_id,
            "instance_id": instance_id,
            "branch_id": branch_id,
            "parent_id": parent_id,
        },
    )
    report = record_evidence_lifecycle_report(
        instance_id=instance_id,
        branch_id=branch_id,
        profile_id=profile_id,
        agent_id=agent_id,
        release_profile=release_profile,
        evidence=evidence,
        lifecycle_transition=transition,
        change_payload=change_payload,
        parent_id=parent_id,
        submission_sequence=submission_sequence,
    )
    receipt = {
        "submission_sequence": report["report_submission_sequence"],
        "component_id": report["report_components"]["special_id"],
        "git_commit": report["git"]["commit"],
        "ledger_generation": report["ledger_generation"],
        "ledger_projection_hash": report["ledger_projection_hash"],
    }
    lifecycle = client.finalize_research_evidence_lifecycle(
        transition["transition_ref"], receipt,
    )
    updated = client.get_research_evidence(evidence_ref)
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    library.record_evidence(updated)
    library.rebuild_index()
    emit({
        "status": lifecycle["status"],
        "evidence_ref": evidence_ref,
        "lifecycle": lifecycle,
        "report": report,
        "next_actions": [{
            "action": (
                "review_affected_obligations"
                if action == "exclude"
                else "add_new_evidence_use_if_needed"
            ),
            "argv": [
                "factortester", "research", "graphs", "obligation", "status",
                instance_id, branch_id,
                "--profile-id", profile_id,
                "--agent-id", agent_id,
            ],
        }],
    }, as_json)


def _read_lifecycle_change(path: Path) -> dict[str, Any]:
    value = read_object(path, "Evidence lifecycle change")
    required = {
        "expected_projection_hash", "research_cycle", "obligation_delta",
        "obligation_presentations", "reason_markdown",
    }
    if set(value) != required:
        raise click.ClickException(
            "Evidence lifecycle change fields must be "
            "expected_projection_hash, research_cycle, obligation_delta, "
            "obligation_presentations, reason_markdown; EvidenceUse removals "
            "are derived by the CLI"
        )
    if (
        not isinstance(value["expected_projection_hash"], str)
        or not isinstance(value["research_cycle"], dict)
        or not isinstance(value["obligation_delta"], list)
        or not isinstance(value["obligation_presentations"], dict)
        or not isinstance(value["reason_markdown"], str)
        or not value["reason_markdown"].strip()
    ):
        raise click.ClickException(
            "Evidence lifecycle change field types are invalid"
        )
    validate_research_cycle_envelope(value["research_cycle"])
    return value


@click.command("admit-graph")
@click.argument("evidence_ref")
@click.option("--instance-id", required=True)
@click.option("--branch-id", required=True)
@click.option(
    "--qualification",
    type=click.Choice(["unreviewed", "eligible", "limited", "rejected"]),
    required=True,
)
@click.option("--note", default="")
@click.option("--json", "as_json", is_flag=True)
def admit_graph(
    evidence_ref: str,
    instance_id: str,
    branch_id: str,
    qualification: str,
    note: str,
    as_json: bool,
) -> None:
    value = client_from_config().admit_research_evidence_for_graph(
        evidence_ref,
        instance_id=instance_id,
        branch_id=branch_id,
        qualification=qualification,
        note=note,
    )
    emit(value, as_json)


def _guide(topic: str) -> dict[str, Any]:
    steps = {
        "overview": [
            "先冻结主 Agent 起草的义务",
            "按产品、因子版本和时间范围搜索 Evidence",
            "没有兼容结果时再捕获来源和片段",
            "最后通过 obligation change 绑定使用理由",
        ],
        "search": [
            "先使用结构化 scope，再使用系统 Facet 和 Agent Tag",
            "因子集合必须使用完整冻结记录对应的 factor-set:v2 target_ref",
            "成员 Evidence 不会自动提升为集合 Evidence；集合结论必须明确绑定集合范围",
        ],
        "capture": [
            "优先复用外部 Web 链接、权威 API、Terminal 或 Job 来源",
            "一个来源可以创建多个片段，不得直接充当 Evidence",
            "Agent 自写报告、审计 Markdown 和手工复制输出不得作为来源",
            "本地文件仅接受带权威下载链路或 Git commit/blob 的 provenance",
            "下载脚本和请求参数只证明获取链路，不能代替原始内容",
        ],
        "fragment": ["选择精确字段、行、生成物或时间点并冻结内容哈希"],
        "create": [
            "Evidence 必须引用至少一个精确 fragment_ref",
            "Evidence 陈述不得超过来源片段能证明的范围",
            "数据能力结果应绑定 CLI 返回的冻结 profile_ref，推进时不得重复扫描",
        ],
        "tag": ["先 propose；仅在现有标签不适用时 create"],
        "bind": [
            "EvidenceUse 必须包含义务、小类、理由和资格",
            "当前研究主体是因子集合时，requested_scope 必须保留精确 factor-set:v2 引用",
        ],
        "exclude": [
            "exclude 必须绑定当前 Graph branch、Agent 和明确 parent_id",
            "CLI 自动解除本分支全部 EvidenceUse 并重算义务覆盖",
            "必要义务状态变化与排除裁决在同一报告/Git 提交中登记",
            "restore 只恢复可发现资格，不会恢复旧 EvidenceUse",
        ],
    }[topic]
    next_action = {
        "overview": ["factortester", "research", "evidence", "guide", "search", "--json"],
        "search": ["factortester", "research", "evidence", "search", "--json"],
        "capture": ["factortester", "research", "evidence", "source", "--help"],
        "fragment": ["factortester", "research", "evidence", "fragment", "add", "--help"],
        "create": ["factortester", "research", "evidence", "create", "--help"],
        "tag": ["factortester", "research", "evidence", "tag", "list", "--json"],
        "bind": ["factortester", "research", "graphs", "obligation", "change", "--help"],
        "exclude": ["factortester", "research", "evidence", "exclude", "--help"],
    }[topic]
    return {
        "topic": topic,
        "rules": steps,
        "next_actions": [{"action": topic, "argv": next_action}],
    }
