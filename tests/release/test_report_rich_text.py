"""Rich-text report authoring acceptance seams."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click import ClickException
from click.testing import CliRunner

from tools.cli.commands import research_report_component
from tools.cli.commands.research_report import report
from tools.cli.commands.research_report_common import component_content, rich_body
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_rich_text import (
    validate_rich_text,
)
from tools.cli.release.research_reporting.authoring.declared_links import (
    declared_inline_links,
)
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    initialize_tree,
)
from tools.cli.release.research_reporting.authoring.tree_schema import validate_node
from tools.cli.release.research_reporting.workspace import initialize_work_package


def test_rich_body_accepts_portable_markdown(tmp_path: Path) -> None:
    source = tmp_path / "finding.md"
    source.write_text(
        "结论含 `SgCPS` 与 \\(IC_t\\)。\n\n"
        "```python\nscore = close.pct_change()\n```\n\n"
        "| 指标 | 值 |\n| --- | ---: |\n| IC | 0.03 |\n\n"
        "$$\nIR = \\frac{\\mu}{\\sigma}\n$$\n",
        encoding="utf-8",
    )

    body = rich_body(body=None, body_file=source)
    assert "score" in body
    assert validate_rich_text(body, field="node.body") == body


def test_list_component_accepts_repeated_items_and_exports_markdown(
    tmp_path: Path,
) -> None:
    content = component_content(
        kind="list", content_file=None, code_file=None,
        language="text", latex=None, fallback="",
        items=("主结论含 `SgCPS`", "证据见 [任务](factortester://job/job%3A1)"),
        ordered=False,
    )
    node = validate_node({
        "schema_version": 1, "node_id": "findings", "kind": "list",
        "title": "研究发现", "body": "", "display_kind": "",
        "created_at": 0.0, "children": [], "bindings": [],
        "content": content,
    })

    assert node["content"]["style"] == "unordered"
    assert [item["text"] for item in node["content"]["items"]] == [
        "主结论含 `SgCPS`",
        "证据见 [任务](factortester://job/job%3A1)",
    ]


def test_list_component_rejects_missing_items() -> None:
    with pytest.raises(ClickException, match="requires --item"):
        component_content(
            kind="list", content_file=None, code_file=None,
            language="text", latex=None, fallback="",
        )


@pytest.mark.parametrize("body", [
    '{"columns":["指标"],"rows":[["IC"]]}',
    "```python\nunclosed = True",
    "| 指标 | 值 |\n| --- | --- |\n| IC | 0.03 | extra |",
    "$$\nIR = mu / sigma",
])
def test_report_tree_rejects_invalid_rich_body_before_writing(
    tmp_path: Path, body: str,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    with pytest.raises(ValueError):
        add_component(
            package_root=package, branch_id="main", component_id="chapter",
            kind="chapter", title="发现", parent_id=None, body=body,
            content=None, display_kind="",
        )

    assert created["head"]["generation"] == 0
    assert not (created["paths"]["nodes"] / "chapter").exists()


def test_report_batch_rejects_invalid_rich_body_before_writing(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main", report_id="report-wp",
        title="研究报告",
    )

    with pytest.raises(ValueError, match="JSON payload, not rich text"):
        apply_batch(
            package_root=package, branch_id="main", operations=[{
                "op": "add", "component_id": "chapter", "kind": "chapter",
                "title": "发现", "parent_id": None,
                "body": '{"columns":["指标"],"rows":[["IC"]]}',
                "content": None, "display_kind": "", "bindings": [],
            }],
        )

    assert created["head"]["generation"] == 0
    assert not (created["paths"]["nodes"] / "chapter").exists()


def test_report_tree_rejects_oversized_markdown_table() -> None:
    body = "| A | B |\n| --- | --- |\n" + "| 1 | 2 |\n" * 201

    with pytest.raises(ValueError, match="inline Markdown table limit"):
        validate_rich_text(body, field="node.body")


def test_rich_body_accepts_table_formulas_and_code_with_vertical_bars() -> None:
    body = (
        "| 指标 | 定义 |\n"
        "| --- | --- |\n"
        "| 范数 | \\(\\lVert r_t \\mid r_{t-1}\\rVert\\) |\n"
        "| 掩码 | `left | right` |\n"
    )

    assert validate_rich_text(body, field="node.body") == body


def test_rich_body_accepts_canonical_typed_domain_links() -> None:
    reference = typed_markdown_link(
        kind="evidence", target_ref="evidence:ic-2025", label="IC 检验",
    )

    assert validate_rich_text(f"结果见 {reference}", field="node.body")
    with pytest.raises(ValueError, match="Markdown link syntax"):
        validate_rich_text(
            "结果见 factortester://evidence/evidence%3Aic-2025",
            field="node.body",
        )
    with pytest.raises(ValueError, match="canonical"):
        validate_rich_text(
            "[IC](factortester://evidence/evidence:ic-2025)",
            field="node.body",
        )


def test_declared_links_preserve_the_agent_authored_kind_target_and_label() -> None:
    body = (
        "使用 [工业硅](factortester://product/"
        "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE) 验证"
    )

    references = declared_inline_links(body, field="node.body")

    assert [(item.kind, item.target_ref, item.label) for item in references] == [(
        "product",
        "Product/Futures/CNFutures/_products/SI.GFE",
        "工业硅",
    )]


def test_declared_link_round_trip_preserves_brackets_in_factor_label() -> None:
    value = typed_markdown_link(
        kind="factor",
        target_ref="factor:v2:" + "a" * 43,
        label="SgCPS|P:[CA]|N:20d",
    )

    assert r"P:\[CA\]" in value
    reference = declared_inline_links(value, field="node.body")[0]
    assert reference.label == "SgCPS|P:[CA]|N:20d"


def test_versioned_factor_and_resolved_domain_links_are_valid() -> None:
    factor = typed_markdown_link(
        kind="factor",
        target_ref="factor-family:v2:" + "c" * 43,
        label="SgCPS",
    )
    product = typed_markdown_link(
        kind="product",
        target_ref="Product/Futures/CNFutures/_products/SI.GFE",
        label="工业硅",
    )
    profile = typed_markdown_link(
        kind="profile", target_ref="profile:maxa", label="MaxA",
    )
    profile_revision = typed_markdown_link(
        kind="profile_revision",
        target_ref=f"profile-revision:v1:maxa:sha256:{'3' * 64}",
        label="MaxA 配置版本",
    )
    contract = typed_markdown_link(
        kind="contract",
        target_ref=(
            "Product/FuturesContract/CNFuturesContract/_products/"
            "GFEX|F|SI|2605"
        ),
        label="工业硅 2609",
    )
    continuous = typed_markdown_link(
        kind="continuous_contract",
        target_ref=(
            "Product/Futures/CNFutures/_products/SI.GFE/"
            "_series/primary_raw"
        ),
        label="工业硅主力连续",
    )

    assert validate_rich_text(
        f"比较 {factor}、{product}、{profile}、{profile_revision}、"
        f"{contract} 与 {continuous}",
        field="node.body",
    )
    with pytest.raises(ValueError, match="profile reference"):
        typed_markdown_link(
            kind="profile", target_ref="profile:", label="MaxA",
        )


def test_legacy_frozen_factor_links_remain_readable() -> None:
    legacy_factor = (
        "factor:v1:profile-maxa:cHVibGljX2ZhY3RvcnMvTW1UcmVuZC5weQ:"
        "TW1UcmVuZHxOOjIwZA:"
        f"{'a' * 40}:{'b' * 40}"
    )
    legacy_family = (
        "factor-family:v1:profile-maxa:"
        "cHVibGljX2ZhY3RvcnMvTW1UcmVuZC5weQ:TW1UcmVuZA:"
        f"{'a' * 40}:{'b' * 40}"
    )
    legacy_set = (
        "factor-set:v1:profile-maxa:"
        "LmZhY3RvcnRlc3Rlci9mYWN0b3Itc2V0cy9tb21lbnR1bS5qc29u:"
        "bW9tZW50dW0:"
        f"{'a' * 40}:{'b' * 40}"
    )

    assert validate_rich_text(
        typed_markdown_link(
            kind="factor", target_ref=legacy_factor, label="MmTrend|N:20d",
        ),
        field="node.body",
    )
    assert validate_rich_text(
        typed_markdown_link(
            kind="factor", target_ref=legacy_family, label="MmTrend",
        ),
        field="node.body",
    )
    assert validate_rich_text(
        typed_markdown_link(
            kind="factor", target_ref=legacy_set, label="动量集合",
        ),
        field="node.body",
    )


def test_incomplete_legacy_factor_links_remain_rejected() -> None:
    with pytest.raises(ValueError, match="frozen formula"):
        typed_markdown_link(
            kind="factor",
            target_ref="factor:v1:profile-maxa:path:alias:commit:blob",
            label="不完整引用",
        )


def test_typed_factor_set_uses_the_factor_link_kind() -> None:
    target = "factor-set:v2:" + "b" * 43

    link = typed_markdown_link(
        kind="factor", target_ref=target, label="动量因子集合",
    )

    assert link.startswith("[动量因子集合](factortester://factor/")


def test_typed_links_are_valid_in_component_titles_and_table_cells() -> None:
    link = typed_markdown_link(
        kind="job", target_ref="job:backtest-1", label="回测任务",
    )
    node = validate_node({
        "schema_version": 1, "node_id": "table", "kind": "table",
        "title": f"结果 {link}", "body": "", "display_kind": "",
        "created_at": 0.0, "children": [], "bindings": [],
        "content": {"columns": ["来源"], "rows": [[link]]},
    })
    assert node["content"]["rows"][0][0] == link


def test_report_add_reads_rich_body_file_and_reports_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root = tmp_path / "client"
    profile_root = tmp_path / "profile"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=profile_root,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究报告", "status": "pending",
        "scope": {"factor_families": []}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:ws", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "report-branch:main", "checkpoint_ref": "",
        "evidence_refs": [], "timeline_refs": [], "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=profile_root, work_package_id="wp", branch_id="main",
        workspace_id="ws", title="研究报告", branch_ref="report-branch:main",
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda _path: client_root,
    )
    source = tmp_path / "finding.md"
    source.write_text("研究结论含 `SgCPS`。", encoding="utf-8")

    result = CliRunner().invoke(report, [
        "add", "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main", "--component-id", "chapter", "--kind",
        "chapter", "--title", "发现", "--body-file", str(source), "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["body_format"] == "restricted_markdown"


def test_report_add_uses_requirement_options_without_chip_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root = tmp_path / "client"
    profile_root = tmp_path / "profile"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=profile_root,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "研究报告", "status": "pending",
        "scope": {"factor_families": []}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "workspace:ws", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "report-branch:main", "checkpoint_ref": "",
        "evidence_refs": [], "timeline_refs": [], "artifacts": [],
        "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialize_work_package(
        workspace_root=profile_root, work_package_id="wp", branch_id="main",
        workspace_id="ws", title="研究报告", branch_ref="report-branch:main",
    )
    monkeypatch.setattr(
        research_report_component, "load_profile_root", lambda _path: client_root,
    )

    result = CliRunner().invoke(report, [
        "add", "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main", "--component-id", "finding", "--kind",
        "chapter", "--title", "结果", "--body", "结果正文",
        "--report-requirement-id", "report.node.result",
        "--report-subject-ref", "node:result_audit",
        "--report-content-kind", "entry", "--json",
    ])

    assert result.exit_code == 0, result.output
    source = (
        profile_root / "research" / "wp" / "branches" / "main" / "authoring"
    )
    head = json.loads((source / "HEAD.json").read_text(encoding="utf-8"))
    root = json.loads((source / head["root_ref"]).read_text(encoding="utf-8"))
    finding = json.loads((source / root["children"][0]["ref"]).read_text(encoding="utf-8"))
    assert finding["body"] == "结果正文"
    assert "factortester://report_requirement/" not in finding["body"]
    assert finding["bindings"][0]["kind"] == "report_requirement"
    assert CliRunner().invoke(report, ["chip", "--help"]).exit_code != 0


def test_report_add_rejects_inline_and_file_body_together(tmp_path: Path) -> None:
    source = tmp_path / "finding.md"
    source.write_text("正文", encoding="utf-8")

    with pytest.raises(ClickException, match="mutually exclusive"):
        rich_body(body="正文", body_file=source)


def test_plain_list_with_factor_alias_pipes_is_not_a_markdown_table() -> None:
    value = (
        "- 使用 `SgCPSVol|P:[CA]|N:2m|V:20d|$F:1m` 作为候选。\n"
        "- 下一项继续说明研究约束。"
    )

    assert validate_rich_text(value, field="body") == value
