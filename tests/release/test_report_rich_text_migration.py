from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.maintenance.rich_text_lists import (
    inspect_rich_text_migration,
    migrate_rich_text,
    normalize_text,
)
from tools.cli.release.research_reporting.maintenance.rich_text_normalization import (
    semantic_text,
)
from tools.cli.release.research_reporting.authoring.inline_code_policy import (
    format_inline_code,
    format_inline_math,
)


def test_normalization_lists_dense_prose_and_links_existing_references(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    note = package / "grill" / "core-signal.md"
    note.parent.mkdir(parents=True)
    note.write_text("evidence", encoding="utf-8")
    source = (
        "第一项结论说明核心信号、信息来源、比较对象、适用时间尺度、"
        "预期方向与失效条件，并记录这些约束为何需要在测试前冻结。"
        "第二项结论记录候选构造、数据可用性、执行时点、费用假设与"
        "样本外边界，并引用 "
        "grill/core-signal.md 与 https://example.com/research 。"
    )

    value, reasons = normalize_text(
        source, package_root=package, listify=True,
    )

    assert value == (
        "- 第一项结论说明核心信号、信息来源、比较对象、适用时间尺度、"
        "预期方向与失效条件，并记录这些约束为何需要在测试前冻结。\n"
        "- 第二项结论记录候选构造、数据可用性、执行时点、费用假设与"
        "样本外边界，并引用 [grill/core-signal.md](grill/core-signal.md) "
        "与 [https://example.com/research](https://example.com/research) 。"
    )
    assert reasons == ["file", "url", "list"]
    assert semantic_text(value) == semantic_text(source)


def test_migration_switches_head_once_and_preserves_component_identity(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    note = package / "assets" / "audit.md"
    note.parent.mkdir(parents=True)
    note.write_text("audit", encoding="utf-8")
    initialized = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="假设登记", parent_id=None, body="",
        content=None, display_kind="", include_snapshot=False,
    )
    source = (
        "第一项结论用于解释研究约束、适用范围、信息来源、比较对象、"
        "时间尺度、预期方向和可证伪条件，并说明这些字段必须先冻结。"
        "第二项结论记录数据可用性、验证结果、执行语义、费用假设、"
        "样本外边界与后续动作，并要求结论与原始证据保持可追溯关系。"
        "详细材料见 assets/audit.md。"
    )
    add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="entry", title="研究发现", parent_id="chapter", body=source,
        content=None, display_kind="", include_snapshot=False,
    )
    before = load_snapshot(package_root=package, branch_id="main")

    plan = inspect_rich_text_migration(
        package_root=package, branch_id="main",
    )
    migrated = migrate_rich_text(package_root=package, branch_id="main")
    after = load_snapshot(package_root=package, branch_id="main")

    assert plan["change_count"] == 1
    assert migrated["head"]["generation"] == before["head"]["generation"] + 1
    assert [item["component_id"] for item in before["components"]] == [
        item["component_id"] for item in after["components"]
    ]
    finding = next(
        item for item in after["components"]
        if item["component_id"] == "finding"
    )
    assert finding["parent_id"] == "chapter"
    assert finding["body"].startswith("- 第一项结论")
    assert "[assets/audit.md](assets/audit.md)" in finding["body"]
    assert note.read_text(encoding="utf-8") == "audit"

    repeated = migrate_rich_text(package_root=package, branch_id="main")
    assert repeated["migrated"] is False
    assert repeated["head"]["generation"] == migrated["head"]["generation"]
    assert initialized["head"]["report_id"] == after["head"]["report_id"]


def test_normalization_does_not_rewrite_code_or_existing_markdown_links(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    note = package / "grill" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("note", encoding="utf-8")
    source = (
        "保留 `grill/note.md`，并保留"
        "[具名材料](grill/note.md)。"
    )

    value, reasons = normalize_text(
        source, package_root=package, listify=False,
    )

    assert value == source
    assert reasons == []


def test_inline_code_policy_formats_technical_tokens_but_not_proper_names() -> None:
    source = (
        "使用 SgCPSVol|P:[CA]|N:2m、RunSpec、screen 与 --role；"
        "框架参考 FactorTester 和 NautilusTrader；"
        "来源 White (2000), Harvey, Liu and Zhu (2016)。"
    )

    value, tokens = format_inline_code(source)

    assert value == (
        "使用 `SgCPSVol|P:[CA]|N:2m`、`RunSpec`、`screen` 与 `--role`；"
        "框架参考 FactorTester 和 NautilusTrader；"
        "来源 White (2000), Harvey, Liu and Zhu (2016)。"
    )
    assert tokens == ["SgCPSVol|P:[CA]|N:2m", "RunSpec", "screen", "--role"]


def test_migration_distinguishes_math_code_and_english_prose() -> None:
    source = (
        "当前收盘相对前一日收盘的收益均值；"
        "并非 O_t 相对 C_{t-1} 的隔夜 gap"
    )

    math_value, math_tokens = format_inline_math(source)
    value, code_tokens = format_inline_code(math_value)

    assert value == (
        r"当前收盘相对前一日收盘的收益均值；"
        r"并非 \(O_t\) 相对 \(C_{t-1}\) 的隔夜 gap"
    )
    assert math_tokens == ["O_t", "C_{t-1}"]
    assert code_tokens == []

    equation, equation_tokens = format_inline_math(
        "MmTrend=(P_t-P_{t-N})/mean_N(P)。"
    )
    assert equation == r"MmTrend=\((P_t-P_{t-N})/mean_N(P)\)。"
    assert equation_tokens == ["(P_t-P_{t-N})/mean_N(P)"]


def test_inline_code_policy_keeps_one_expression_and_parameter_tokens() -> None:
    expression = (
        "(P - P.shift(N)) / rolling_mean(N, P)；"
        "低频；默认 N=1d，最终 N 与 $F 待 TrialPlan 冻结"
    )

    value, tokens = format_inline_code(expression)

    assert value == (
        "`(P - P.shift(N)) / rolling_mean(N, P)`；"
        "低频；默认 `N=1d`，最终 `N` 与 `$F` 待 `TrialPlan` 冻结"
    )
    assert tokens == [
        "(P - P.shift(N)) / rolling_mean(N, P)",
        "N=1d",
        "N",
        "$F",
        "TrialPlan",
    ]


def test_inline_code_policy_does_not_consume_a_list_marker() -> None:
    value, tokens = format_inline_code(
        "- CLOSE 与 top-k；统计 slope/R2/t-stat/residual std）"
    )

    assert value == (
        "- `CLOSE` 与 `top-k`；"
        "统计 `slope/R2/t-stat/residual std`）"
    )
    assert tokens == ["CLOSE", "top-k", "slope/R2/t-stat/residual std"]


def test_inline_code_policy_keeps_one_quoted_error_message() -> None:
    value, tokens = format_inline_code(
        "配置拒绝“factor aliases are not registered in workspace”。"
    )

    assert value == (
        "配置拒绝“`factor aliases are not registered in workspace`”。"
    )
    assert tokens == ["“factor aliases are not registered in workspace”"]


def test_migration_never_infers_domain_references_from_prose(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    source = "比较 SgCPSVol|P:[CA]|N:2m 与 SI.GFE。"

    value, reasons = normalize_text(
        source, package_root=package, listify=False,
    )

    assert value == "比较 `SgCPSVol|P:[CA]|N:2m` 与 `SI.GFE`。"
    assert reasons == ["inline_code"]
    assert semantic_text(value) == semantic_text(source)

    parameter, parameter_reasons = normalize_text(
        "参数 P 与产品 P.DCE。", package_root=package, listify=False,
    )
    assert parameter == "参数 `P` 与产品 `P.DCE`。"
    assert parameter_reasons == ["inline_code"]
