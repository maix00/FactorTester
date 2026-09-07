"""CLI commands for the durable Research catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.release.locations import default_client_root
from tools.cli.release.research_reporting.public_research.client import (
    PublicResearchClient,
)


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
        type=click.Choice(("private", "superiors", "authorized", "public")),
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
        type=click.Choice(("private", "superiors", "authorized", "public")),
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

    @research.command("member-remove")
    @click.argument("research_id")
    @click.option("--profile", "profile_ref", required=True)
    @friendly_errors
    def remove_member(research_id: str, profile_ref: str) -> None:
        """从 Research 移除一个 Profile，并停用其 Research Workspace。"""
        click.echo(_json(client_from_config().remove_research_member(
            research_id, profile_ref,
        )))

    @research.command("remove")
    @click.argument("research_id")
    @friendly_errors
    def remove_research(research_id: str) -> None:
        """删除当前端点创建的 Research；远端投影不可移除。"""
        click.echo(_json(client_from_config().remove_research(research_id)))

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

    @research.command("report-create")
    @click.argument("research_id")
    @click.option("--title", required=True, help="研究报告标题。")
    @click.option("--profile", "profile_ref", required=True)
    @click.option(
        "--visibility",
        type=click.Choice(("private", "superiors", "authorized", "public")),
        default="private",
        show_default=True,
    )
    @click.option("--authorized-user", multiple=True, help="授权用户，可重复。")
    @click.option("--report-id", default="", help="恢复同一研究中已创建的报告，不再新建目录记录。")
    @friendly_errors
    def create_report(
        research_id: str,
        title: str,
        profile_ref: str,
        visibility: str,
        authorized_user: tuple[str, ...],
        report_id: str,
    ) -> None:
        """在 Research 中新建一个由 Profile 撰写的报告空间。"""
        from tools.cli.release.local_profile import LocalProfileStore
        from tools.cli.release.research_reporting.report_space import initialize_report_space

        client = client_from_config()
        store = LocalProfileStore(default_client_root())
        # Validate local Profile before creating a remote catalog record.
        store.load(profile_ref)
        if report_id:
            report = next((item for item in client.research_manifest(research_id).get("reports", [])
                           if item.get("report_id") == report_id), None)
            if report is None:
                raise click.ClickException("当前研究中找不到指定报告")
        else:
            report = client.create_research_report(research_id, {
                "title": title, "profile_ref": profile_ref,
                "visibility": visibility, "authorized_users": list(authorized_user),
            })
        initialized = initialize_report_space(store, profile_ref, report)
        # The existing server report reader sees the Profile-owned tree; client
        # reports continue to use the existing explicit publication workflow.
        import os
        if os.environ.get("FACTORTESTER_AGENT_CAPABILITY_FILE"):
            client.register_research_report(research_id, {
                "report_id": report["report_id"], "title": report["title"],
                "profile_ref": profile_ref, "workspace_id": report["workspace_id"],
                "build_source": "server_agent", "source_ref": initialized["source_ref"],
                "visibility": report["visibility"], "authorized_users": report.get("authorized_users", []),
            })
        click.echo(_json(initialized))


    @research.command("report-update")
    @click.argument("research_id")
    @click.argument("report_id")
    @click.option(
        "--visibility",
        type=click.Choice(("private", "superiors", "authorized", "public")),
    )
    @click.option("--authorized-user", multiple=True, help="替换授权用户列表。")
    @click.option("--clear-authorized-users", is_flag=True)
    @friendly_errors
    def update_report(
        research_id: str,
        report_id: str,
        visibility: str | None,
        authorized_user: tuple[str, ...],
        clear_authorized_users: bool,
    ) -> None:
        """更新 Report 独立可见性。"""
        if clear_authorized_users and authorized_user:
            raise click.ClickException(
                "--clear-authorized-users 不能与 --authorized-user 同时使用"
            )
        payload: dict[str, Any] = {}
        if visibility is not None:
            payload["visibility"] = visibility
        if clear_authorized_users:
            payload["authorized_users"] = []
        elif authorized_user:
            payload["authorized_users"] = list(authorized_user)
        if not payload:
            raise click.ClickException("至少提供一个要更新的字段")
        click.echo(_json(client_from_config().update_research_report(
            research_id, report_id, payload,
        )))

    @research.command("report-remove")
    @click.argument("research_id")
    @click.argument("report_id")
    @friendly_errors
    def remove_report(research_id: str, report_id: str) -> None:
        """归档 Research 中的一个研究报告空间。"""
        click.echo(_json(client_from_config().remove_research_report(
            research_id, report_id,
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

    @research.command("migrate-existing-reports")
    @click.option("--apply", is_flag=True, help="执行计划；省略时只显示发现结果。")
    @friendly_errors
    def migrate_existing_reports(apply: bool) -> None:
        """发现客户端、服务器 Agent 与公共发布中的旧报告并显式迁移。"""
        client = client_from_config()
        local_records = PublicResearchClient(
            default_client_root(),
        ).local_report_migration_records(apply_identities=apply)
        remote = client.discover_research_report_migration(apply=apply)
        if not apply:
            click.echo(_json({
                "status": "planned",
                "local_count": len(local_records),
                "remote_count": int(remote.get("count") or 0),
                "records": local_records + list(remote.get("records") or []),
            }))
            return
        local = client.migrate_research_reports(local_records)
        click.echo(_json({
            "status": "completed",
            "local": local,
            "remote": remote,
        }))

    @research.command("manifest")
    @click.argument("research_id")
    @friendly_errors
    def manifest(research_id: str) -> None:
        """读取共享 Research 的精简关系清单（不下载正文或生成物）。"""
        click.echo(_json(client_from_config().research_manifest(research_id)))


__all__ = ["register_research_catalog_commands"]
