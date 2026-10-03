"""Structured discovery for report move and replacement operations."""

from __future__ import annotations

from typing import Any

import click

from .research_report_common import output


_SCOPE = (
    "--profile <profile> --report-workspace-id <package> --branch-id <branch>"
)


def _move_guide() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "move",
        "purpose": "移动或重新排序一个既有报告组件并保留稳定 component_id 和子树",
        "inspect_command": f"factortester research reports show {_SCOPE} --json",
        "operations_file_template": {
            "operations": [{
                "op": "move",
                "component_id": "<existing-component-id>",
                "parent_id": "<new-parent-component-id>",
                "after_component_id": "<optional-sibling-component-id>",
            }],
        },
        "required_fields": ["op", "component_id", "parent_id"],
        "optional_fields": ["after_component_id"],
        "rules": [
            "省略 after_component_id 时移动到新父级的第一个位置",
            "after_component_id 必须是新父级已有的直接子项",
            "不能移动 root、系统容器或造成层级循环",
            "父子组件类型必须符合报告树层级合同",
        ],
        "submit_command": (
            f"factortester research reports add-batch {_SCOPE} "
            "--operations-file <operations.json> --json"
        ),
    }


def _replace_guide() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "replace",
        "purpose": "替换一个既有组件的作者字段并保留类型、父级、子项和工作流绑定",
        "inspect_command": f"factortester research reports show {_SCOPE} --json",
        "operations_file_template": {
            "operations": [{
                "op": "replace",
                "component_id": "<existing-component-id>",
                "title": "<complete-title-or-empty-string>",
                "body": "<complete-restricted-markdown-or-empty-string>",
                "content": None,
                "display_kind": "<complete-display-kind-or-empty-string>",
            }],
        },
        "required_fields": [
            "op", "component_id", "title", "body", "content",
            "display_kind",
        ],
        "forbidden_fields": ["bindings", "parent_id"],
        "rules": [
            "先从 report show 读取当前组件，对未修改字段原样回填完整值",
            "不能改变组件 kind、parent_id 或 children",
            "不要提交 bindings；CLI 从正文中的显式类型化链接重新生成引用绑定",
            "系统容器和系统生命周期特殊小节不能由 Agent 替换",
        ],
        "submit_command": (
            f"factortester research reports add-batch {_SCOPE} "
            "--operations-file <operations.json> --json"
        ),
    }


_GUIDES = {
    "move": _move_guide,
    "replace": _replace_guide,
}


@click.command("mutation-guide")
@click.option(
    "--operation",
    type=click.Choice(sorted(_GUIDES)),
    required=True,
    help="读取移动或内容替换的当前结构化合同",
)
@click.option("--json", "as_json", is_flag=True)
def report_mutation_guide(operation: str, as_json: bool) -> None:
    """Return the current machine-readable move or replace contract."""
    value = _GUIDES[operation]()
    value["next_actions"] = [
        {"action": "inspect", "command": value["inspect_command"]},
        {"action": "submit", "command": value["submit_command"]},
    ]
    output(value, as_json)
