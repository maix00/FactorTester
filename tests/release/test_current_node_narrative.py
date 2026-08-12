from tools.cli.release.research_reporting.publisher.current_node_narrative import (
    narrative,
)


def _item(*, title: str, role: str, subject_ref: str, content: dict) -> dict:
    binding = {
        "report_requirement_id": "report.node.trial_execution.action",
        "subject_ref": subject_ref,
    }
    return {
        **binding,
        "title_zh": title,
        "item_hash": subject_ref.removeprefix("action:").ljust(64, "a")[:64],
        "content": content,
        "links": [],
        "report_binding": binding,
        "chapter_ref": "node:trial_execution",
        "section_role": role,
    }


def test_current_node_narrative_keeps_domain_sections_separate() -> None:
    value = narrative(
        [
            _item(
                title="试验结果 · 截面 IC", role="trial_result",
                subject_ref="action:ic",
                content={"kind": "table", "columns": ["指标"], "rows": []},
            ),
            _item(
                title="审计与义务变化 · 截面 IC", role="obligation_changes",
                subject_ref="audit:ic",
                content={"kind": "list", "rows": []},
            ),
        ],
        recorded_at=1.0, current_node="trial_execution",
    )

    assert [item["section_role"] for item in value["sections"]] == [
        "trial_result", "obligation_changes",
    ]
    assert [item["title"] for item in value["sections"]] == [
        "试验结果 · 截面 IC", "审计与义务变化 · 截面 IC",
    ]
