"""Local skill-use audit, decisions, gaps, and session status."""

from __future__ import annotations

import json

import click

from ..core.evidence import assert_no_legacy_evidence_payload
from ..core.session import (
    load_session,
    mark_factor_improvement_required,
    record_event,
    record_gap,
    record_skill_usage,
    resolve_gap,
    save_session,
)
from .common import echo_json

@click.group("skill-usage")
def skill_usage() -> None:
    """记录仅保存在本地研究过程中的实际 Skill 使用审计。"""


@skill_usage.command("record")
@click.option("--capability-description", required=True)
@click.option("--descriptor-hash", required=True)
@click.option("--skill-name", required=True)
@click.option("--skill-description", required=True)
@click.option("--provider", required=True)
@click.option("--version", required=True)
@click.option("--source-fingerprint", required=True)
@click.option("--approval-ref", required=True)
@click.option(
    "--load-mode",
    type=click.Choice(["loaded", "reused"]),
    required=True,
)
@click.option("--matching-rationale", required=True)
@click.option("--skill-document-tokens", type=click.IntRange(min=0), default=0)
@click.option("--cache-read-tokens", type=click.IntRange(min=0), default=0)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def skill_usage_record(
    ctx: click.Context,
    capability_description: str,
    descriptor_hash: str,
    skill_name: str,
    skill_description: str,
    provider: str,
    version: str,
    source_fingerprint: str,
    approval_ref: str,
    load_mode: str,
    matching_rationale: str,
    skill_document_tokens: int,
    cache_read_tokens: int,
    as_json: bool,
) -> None:
    """记录 Agent 实际选择、加载或复用的 Skill；不上传服务器。"""
    session = load_session(ctx.obj["session_path"])
    try:
        row = record_skill_usage(
            session,
            capability_description=capability_description,
            descriptor_hash=descriptor_hash,
            skill_name=skill_name,
            skill_description=skill_description,
            provider=provider,
            version=version,
            source_fingerprint=source_fingerprint,
            approval_ref=approval_ref,
            load_mode=load_mode,
            matching_rationale=matching_rationale,
            skill_document_tokens=skill_document_tokens,
            cache_read_tokens=cache_read_tokens,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    save_session(session, ctx.obj["session_path"])
    if as_json:
        echo_json({"skill_usage": row})
        return
    click.echo(
        f"{row['usage_id']}: {skill_name} ({load_mode}) "
        f"record_hash={row['record_hash']}"
    )


@skill_usage.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def skill_usage_list(ctx: click.Context, as_json: bool) -> None:
    """读取本地 Skill 使用审计链。"""
    rows = load_session(ctx.obj["session_path"]).skill_usage
    if as_json:
        echo_json({"skill_usage": rows})
        return
    for row in rows:
        click.echo(
            f"{row['usage_id']} {row['skill_name']} "
            f"{row['load_mode']} {row['record_hash']}"
        )
@click.group("decision")
def decision() -> None:
    """Record research decisions that alter the workflow state."""


@decision.command("poor-result")
@click.option("--reason", required=True, help="为什么认为表现不好。")
@click.option("--evidence", default="", help="可选 JSON 或文本证据。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def decision_poor_result(ctx: click.Context, reason: str, evidence: str, as_json: bool) -> None:
    """Mark research as needing factor-workspace improvement."""
    session = load_session(ctx.obj["session_path"])
    evidence_payload: dict[str, object] = {}
    if evidence:
        try:
            parsed = json.loads(evidence)
            evidence_payload = parsed if isinstance(parsed, dict) else {"value": parsed}
        except Exception:
            evidence_payload = {"text": evidence}
    assert_no_legacy_evidence_payload(evidence_payload)
    row = mark_factor_improvement_required(session, reason, evidence=evidence_payload)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        echo_json({"decision": row, "session": session.to_dict()})
        return
    click.echo("状态: factor_improvement_required")
    click.echo("下一步:")
    click.echo("  factortester custom_factors workspace git diff")
    click.echo("  编辑 workspace 中的因子源码/参数")
    click.echo("  factortester custom_factors workspace push")
    click.echo("  重新运行 workspace inspect、IC、类型分析和回测")


@click.group("gap")
def gap() -> None:
    """Manage codebase gaps discovered during research."""


@gap.command("add")
@click.argument("title")
@click.argument("detail", required=False, default="")
@click.pass_context
def gap_add(ctx: click.Context, title: str, detail: str) -> None:
    session = load_session(ctx.obj["session_path"])
    row = record_gap(session, title, detail)
    save_session(session, ctx.obj["session_path"])
    click.echo(f"新增 gap: {row['id']}")


@gap.command("list")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def gap_list(ctx: click.Context, as_json: bool) -> None:
    session = load_session(ctx.obj["session_path"])
    if as_json:
        echo_json({"gaps": session.gaps, "status": session.status})
        return
    if not session.gaps:
        click.echo("无 gap")
        return
    for item in session.gaps:
        click.echo(f"{item['id']} [{item['status']}] {item['title']}")
        if item.get("detail"):
            click.echo(f"  {item['detail']}")


@gap.command("resolve")
@click.argument("gap_id")
@click.option("--note", default="", help="修复说明。")
@click.pass_context
def gap_resolve(ctx: click.Context, gap_id: str, note: str) -> None:
    session = load_session(ctx.obj["session_path"])
    row = resolve_gap(session, gap_id, note=note)
    record_event(session, "gap_resolved", gap_id=gap_id)
    save_session(session, ctx.obj["session_path"])
    click.echo(f"已解决 gap: {row['id']}")


@click.command("status")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """Print current research session state."""
    session = load_session(ctx.obj["session_path"])
    payload = session.to_dict()
    if as_json:
        echo_json(payload)
        return
    click.echo(f"status: {session.status}")
    click.echo(f"operator_mode: {session.operator_mode}")
    click.echo(f"admin_port: {session.admin_port}")
    click.echo(f"factor_families: {', '.join(session.factor_families) or '未设置'}")
    click.echo(f"factors: {', '.join(session.factors) or '未设置'}")
    click.echo(f"configuration_file: {session.configuration_file or '无'}")
    click.echo(f"plan_steps: {len(session.plan)}")
    click.echo(f"open_gaps: {sum(1 for item in session.gaps if item.get('status') == 'open')}")
    source = session.factor_source or {}
    if source:
        click.echo(f"factor_source_files: {source.get('file_count', 0)}")
    click.echo(f"hypotheses_tested: {session.hypotheses_tested}")
    click.echo(f"local_skill_usage_records: {len(session.skill_usage)}")
    click.echo(f"evidence_envelopes: {len(session.evidence_envelopes)}")
