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


def test_migration_links_catalog_factor_family_alias_and_product(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "users" / "user-a" / "profiles" / "maxa"
    package = profile / "research" / "package-a"
    factors = profile / "factor-worktree" / "custom_factors"
    factors.mkdir(parents=True)
    (factors / "SgCPSVol.py").write_text("factor = 1", encoding="utf-8")
    assets = package / "assets"
    assets.mkdir(parents=True)
    (assets / "scope.json").write_text(
        '{"products":["SI.GFE"]}', encoding="utf-8",
    )
    source = "比较 SgCPSVol|P:[CA]|N:2m 与 SI.GFE。"

    value, reasons = normalize_text(
        source, package_root=package, listify=False,
    )

    assert value == (
        "比较 [SgCPSVol](factortester://factor/"
        "factor%3ASgCPSVol%7CP%3A%5BCA%5D%7CN%3A2m)"
        "`|P:[CA]|N:2m` 与 "
        "[SI.GFE](factortester://product/product%3ASI.GFE)。"
    )
    assert reasons == ["factor", "product"]
    assert semantic_text(value) == semantic_text(source)
