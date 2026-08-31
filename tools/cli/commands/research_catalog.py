"""CLI commands for the durable Research catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"无法读取 JSON 文件: {path}") from exc


def register_research_catalog_commands(research: click.Group) -> None:
    """Register Research root operations on the existing ``research`` group."""

    @research.command("list")
    @click.option(
        "--scope",
        type=click.Choice(("all", "mine", "subordinates", "shared")),
        default="all",
        show_default=True,
        help="研究可见范围。",
    )
    @click.option("--include-archived", is_flag=True, help="同时列出已归档研究。")
    @click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
    @friendly_errors
    def list_researches(scope: str, include_archived: bool, as_json: bool) -> None:
        """列出当前用户可见的 Research 根对象。"""
        value = client_from_config().list_researches(
            include_archived=include_archived,
            scope=scope,
        )
        if as_json:
            click.echo(_json(value))
            return
        items = value.get("researches") or value.get("items") or []
        if not items:
            click.echo("暂无研究")
            return
        click.echo("研究 ID\t标题\t所有者\t可见性\t更新时间")
        for item in items:
            click.echo("\t".join([
                str(item.get("research_id") or ""),
                str(item.get("title") or ""),
                str(item.get("owner_ref") or ""),
                str(item.get("visibility") or ""),
                str(item.get("updated_at") or ""),
            ]))

    @research.command("create")
    @click.option("--title", required=True, help="研究标题。")
    @click.option("--description", default="", help="研究说明。")
    @click.option(
        "--visibility",
        type=click.Choice(("private", "authorized", "public")),
        default="private",
        show_default=True,
    )
    @click.option("--authorized-user", multiple=True, help="授权用户，可重复。")
    @click.option("--profile", "profile_ref", default="", help="初始成员 Profile。")
    @friendly_errors
    def create_research(
        title: str,
        description: str,
        visibility: str,
        authorized_user: tuple[str, ...],
        profile_ref: str,
    ) -> None:
        """创建一个 Research 根对象。"""
        click.echo(_json(client_from_config().create_research(
            title=title,
            description=description,
            visibility=visibility,
            authorized_users=list(authorized_user),
            profile_ref=profile_ref,
        )))

    @research.command("show")
    @click.argument("research_id")
    @friendly_errors
    def show_research(research_id: str) -> None:
        """显示 Research 及其成员、工作区、报告和 Evidence 引用。"""
        click.echo(_json(client_from_config().get_research(research_id)))

    @research.command("update")
    @click.argument("research_id")
    @click.option("--title")
    @click.option("--description")
    @click.option(
        "--visibility",
        type=click.Choice(("private", "authorized", "public")),
    )
    @click.option("--status", type=click.Choice(("active", "archived")))
    @click.option("--authorized-user", multiple=True, help="替换授权用户列表。")
    @click.option("--clear-authorized-users", is_flag=True)
    @friendly_errors
    def update_research(
        research_id: str,
        title: str | None,
        description: str | None,
        visibility: str | None,
        status: str | None,
        authorized_user: tuple[str, ...],
        clear_authorized_users: bool,
    ) -> None:
        """更新 Research 元数据或归档状态。"""
        if clear_authorized_users and authorized_user:
            raise click.ClickException(
                "--clear-authorized-users 不能与 --authorized-user 同时使用"
            )
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if visibility is not None:
            payload["visibility"] = visibility
        if status is not None:
            payload["status"] = status
        if clear_authorized_users:
            payload["authorized_users"] = []
        elif authorized_user:
            payload["authorized_users"] = list(authorized_user)
        if not payload:
            raise click.ClickException("至少提供一个要更新的字段")
        click.echo(_json(client_from_config().update_research(research_id, payload)))

    @research.command("member-add")
    @click.argument("research_id")
    @click.option("--principal", "principal_ref", required=True)
    @click.option("--profile", "profile_ref", required=True)
    @click.option(
        "--role",
        type=click.Choice(("owner", "editor", "contributor", "viewer")),
        default="contributor",
        show_default=True,
    )
    @click.option(
        "--status",
        type=click.Choice(("active", "invited", "revoked")),
        default="active",
        show_default=True,
    )
    @friendly_errors
    def add_member(
        research_id: str,
        principal_ref: str,
        profile_ref: str,
        role: str,
        status: str,
    ) -> None:
        """向 Research 添加或更新一个 Profile 成员。"""
        click.echo(_json(client_from_config().add_research_member(
            research_id,
            {
                "principal_ref": principal_ref,
                "profile_ref": profile_ref,
                "role": role,
                "status": status,
            },
        )))

    @research.command("workspace-create")
    @click.argument("research_id")
    @click.option("--principal", "principal_ref", default="")
    @click.option("--profile", "profile_ref", required=True)
    @click.option("--title", default="")
    @friendly_errors
    def create_workspace(
        research_id: str,
        principal_ref: str,
        profile_ref: str,
        title: str,
    ) -> None:
        """为 Research 中的一个 Profile 创建 Research Workspace。"""
        click.echo(_json(client_from_config().create_research_workspace(
            research_id,
            {
                "principal_ref": principal_ref,
                "profile_ref": profile_ref,
                "title": title,
            },
        )))

    @research.command("report-link")
    @click.argument("research_id")
    @click.option("--report-id", required=True)
    @click.option("--title", default="")
    @click.option("--profile", "profile_ref", default="")
    @click.option("--workspace-id", default="")
    @click.option("--build-source", default="client", show_default=True)
    @click.option("--build-source-ref", default="")
    @click.option(
        "--visibility",
        type=click.Choice(("private", "authorized", "public")),
        default="private",
        show_default=True,
    )
    @click.option("--authorized-user", multiple=True)
    @click.option("--source-ref", default="")
    @friendly_errors
    def link_report(
        research_id: str,
        report_id: str,
        title: str,
        profile_ref: str,
        workspace_id: str,
        build_source: str,
        build_source_ref: str,
        visibility: str,
        authorized_user: tuple[str, ...],
        source_ref: str,
    ) -> None:
        """把现有 Report 关联到 Research。"""
        click.echo(_json(client_from_config().register_research_report(
            research_id,
            {
                "report_id": report_id,
                "title": title,
                "profile_ref": profile_ref,
                "workspace_id": workspace_id,
                "build_source": build_source,
                "build_source_ref": build_source_ref,
                "visibility": visibility,
                "authorized_users": list(authorized_user),
                "source_ref": source_ref,
            },
        )))

    @research.command("evidence-link")
    @click.argument("research_id")
    @click.option("--evidence-ref", required=True)
    @click.option("--evidence-owner", "evidence_owner_ref", default="")
    @click.option("--report-id", required=True)
    @click.option("--graph-ref", default="")
    @click.option("--branch-ref", default="")
    @click.option("--job-id", default="")
    @click.option("--profile", "profile_ref", default="")
    @click.option("--purpose", default="")
    @friendly_errors
    def link_evidence(
        research_id: str,
        evidence_ref: str,
        evidence_owner_ref: str,
        report_id: str,
        graph_ref: str,
        branch_ref: str,
        job_id: str,
        profile_ref: str,
        purpose: str,
    ) -> None:
        """把现有 Evidence 引用到 Research/Report。"""
        click.echo(_json(client_from_config().link_research_evidence(
            research_id,
            {
                "evidence_ref": evidence_ref,
                "evidence_owner_ref": evidence_owner_ref,
                "report_id": report_id,
                "graph_ref": graph_ref,
                "branch_ref": branch_ref,
                "job_id": job_id,
                "profile_ref": profile_ref,
                "purpose": purpose,
            },
        )))

    @research.command("migrate-reports")
    @click.option(
        "--file",
        "records_file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @friendly_errors
    def migrate_reports(records_file: Path) -> None:
        """显式、幂等地把已有报告元数据迁移到同名 Research。"""
        value = _read_json(records_file)
        records = value.get("records") if isinstance(value, dict) else value
        if not isinstance(records, list):
            raise click.ClickException("迁移文件必须是报告数组或 {records: []}")
        click.echo(_json(client_from_config().migrate_research_reports(records)))


__all__ = ["register_research_catalog_commands"]
