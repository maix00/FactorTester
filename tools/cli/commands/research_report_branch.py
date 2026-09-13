"""Research report collaboration-branch CLI commands.

Group A (owner/editor) author branches in their own profile workspaces.  Any
reader (group B) may list and read them via ``report branch-list`` /
``report branch-read``.
"""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _json(value: object) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


def register_branch_commands(group: click.Group) -> None:
    group.add_command(branch_list)
    group.add_command(branch_read)
    group.add_command(branch_status)
    group.add_command(branch_reserve)
    group.add_command(branch_publish)


@click.command("branch-list")
@click.argument("research_id")
def branch_list(research_id: str) -> None:
    """列出该研究所有创建者(owner/editor)工作区里的 branch(读者可见)。"""
    _json(client_from_config().collaboration_branches(research_id))


@click.command("branch-read")
@click.argument("target_ref", required=False)
@click.option("--profile-id", default="", help="branch 所属 profile id")
@click.option("--package-id", default="", help="报告包 id")
@click.option("--branch-id", default="", help="branch id")
@click.option("--publication-id", default="", help="branch-list 返回的跨服务器或客户端 publication_id")
@click.option("--chapter-id", default="", help="读取具体章节；省略时只读取目录")
@friendly_errors
def branch_read(
    target_ref: str | None, profile_id: str, package_id: str, branch_id: str,
    publication_id: str = "", chapter_id: str = "",
) -> None:
    """读取某个创建者(branch 归属 principal)工作区里的 branch 内容。"""
    if publication_id:
        if any((target_ref, profile_id, package_id, branch_id)):
            raise click.UsageError("--publication-id 不可与本地服务器分支定位参数混用")
        _json(client_from_config().read_publication_branch(
            publication_id, chapter_id=chapter_id,
        ))
        return
    if chapter_id:
        raise click.UsageError("--chapter-id 需要 --publication-id")
    if not all((target_ref, profile_id, package_id, branch_id)):
        raise click.UsageError("提供 --publication-id，或完整的 target_ref/--profile-id/--package-id/--branch-id")
    _json(client_from_config().read_server_branch(
        target_ref=target_ref,
        profile_id=profile_id,
        package_id=package_id,
        branch_id=branch_id,
    ))


__all__ = ["register_branch_commands", "branch_list", "branch_read"]


@click.command('branch-status')
@click.argument('report_id')
@friendly_errors
def branch_status(report_id: str) -> None:
    """查看报告的共享分支、作者 Profile、版本及预留/可用状态。"""
    _json(client_from_config().report_branch_status(report_id))


@click.command('branch-reserve')
@click.argument('report_id')
@click.option('--profile', 'profile_ref', required=True)
@click.option('--branch-id', required=True)
@click.option('--title', default='')
@click.option('--from-branch', 'source_branch_id', default='')
@click.option('--source-generation', type=click.IntRange(min=0), default=0)
@click.option('--source-revision', default='')
@friendly_errors
def branch_reserve(report_id: str, profile_ref: str, branch_id: str, title: str,
                   source_branch_id: str, source_generation: int, source_revision: str) -> None:
    """为当前用户的确切 Profile 预留独立分支；不会声称内容已传输。"""
    _json(client_from_config().reserve_report_branch(report_id, {
        'profile_ref': profile_ref, 'branch_id': branch_id, 'title': title,
        'source_branch_id': source_branch_id, 'source_generation': source_generation,
        'source_revision': source_revision,
    }))


@click.command('branch-publish')
@click.argument('report_id')
@click.option('--profile', 'profile_ref', required=True)
@click.option('--branch-id', required=True)
@click.option('--publication-id', required=True)
@click.option('--expected-generation', type=click.IntRange(min=0), required=True)
@click.option('--expected-revision', default='')
@friendly_errors
def branch_publish(report_id: str, profile_ref: str, branch_id: str, publication_id: str,
                   expected_generation: int, expected_revision: str) -> None:
    """核验已上传的发布对象，再按旧版本推进共享分支；拒绝覆盖竞争写入。"""
    _json(client_from_config().publish_report_branch(report_id, branch_id, {
        'profile_ref': profile_ref, 'publication_id': publication_id,
        'expected_generation': expected_generation, 'expected_revision': expected_revision,
    }))
