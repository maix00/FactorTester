"""Read-only review of selected source subtrees and their target revision."""
from __future__ import annotations

from pathlib import Path
import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring.tree_copy import plan_subtree_copy
from .research_report_common import scope_options, output
from .research_report_scope import resolve_branch_report_scope, load_authoring


@click.command('copy-preview')
@scope_options
@click.option('--source-profile', default='', help='来源 Profile，省略时使用目标 Profile')
@click.option('--source-work-package-id', default='', help='来源工作包，省略时使用目标工作包')
@click.option('--source-branch-id', required=True)
@click.option('--component-id', multiple=True, required=True, help='完整复制的章节或小节，可多次指定')
@click.option('--parent-id', default='root', show_default=True)
@click.option('--after-component-id', default=None)
@click.option('--copy-id', required=True, help='本次复制的稳定标识；重试使用同一标识')
@click.option('--json', 'as_json', is_flag=True)
@friendly_errors
def copy_preview(profile_id: str, work_package_id: str, branch_id: str,
                 release_profile: Path | None, source_profile: str,
                 source_work_package_id: str, source_branch_id: str,
                 component_id: tuple[str, ...], parent_id: str,
                 after_component_id: str | None, copy_id: str, as_json: bool) -> None:
    """预览已在本端登记的报告分支间章节复制，不修改报告或创建目标分支。"""
    client_root = load_profile_root(release_profile)
    target = resolve_branch_report_scope(client_root=client_root, profile_id=profile_id,
                                        work_package_id=work_package_id, branch_id=branch_id)
    source = resolve_branch_report_scope(client_root=client_root, profile_id=source_profile or profile_id,
                                        work_package_id=source_work_package_id or work_package_id,
                                        branch_id=source_branch_id)
    if source.package_root.resolve() == target.package_root.resolve() and source.branch_id == target.branch_id:
        raise ValueError('source and target must be distinct branches')
    source_owner = (source.profile.get('session_binding') or {}).get('principal_ref')
    target_owner = (target.profile.get('session_binding') or {}).get('principal_ref')
    if not source_owner or source_owner != target_owner:
        raise PermissionError('跨用户来源需要经过 Manager 授权，不能直接读取其本地 Profile')
    plan = plan_subtree_copy(load_authoring(source), load_authoring(target),
                            component_ids=list(component_id), parent_id=parent_id,
                            copy_id=copy_id, after_component_id=after_component_id)
    output({'status': 'preview', **plan}, as_json)
