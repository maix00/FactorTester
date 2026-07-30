import json
from pathlib import Path
from types import SimpleNamespace

import click
from click.testing import CliRunner

from tools.cli.commands.research_report_semantic_migration import (
    _accept_or_reject_existing_plan,
    migrate_component_semantics_command,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component, initialize_tree, load_snapshot,
)
from tools.cli.release.research_reporting.maintenance.component_semantics import (
    _replace_unformatted, migrate_component_semantics,
    prepare_component_semantics,
)


def test_component_migration_preserves_attached_chips_and_adds_typed_links(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="假设登记", parent_id=None, body="",
        content=None, display_kind="",
    )
    add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="entry", title="发现", parent_id="chapter",
        body="比较 SI.GFE 与 RunSpec", content=None, display_kind="",
        bindings=[{
            "binding_id": "workflow-checkpoint", "kind": "checkpoint",
            "target_ref": "trace:one", "label": "检查点", "data": {},
        }],
    )
    components = load_snapshot(
        package_root=package, branch_id="main",
    )["components"]
    import hashlib, json
    identities = sorted(item["component_id"] for item in components)
    digest = hashlib.sha256(
        json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    generated = [{
        "binding_id": "reference-product", "kind": "product",
        "target_ref": "Product/Futures/CNFutures/_products/SI.GFE",
        "label": "SI.GFE", "data": {"description": "工业硅"},
    }]
    monkeypatch.setattr(
        "tools.cli.release.research_reporting.maintenance."
        "component_semantics.preflight_component",
        lambda **_: generated,
    )
    plan = {
        "schema_version": 1, "migration_id": "semantic-v1",
        "reviewed_component_count": len(components),
        "reviewed_component_digest": digest,
        "changes": [{
            "component_id": "finding",
            "replacements": [
                {
                    "field": "body", "source": "SI.GFE",
                    "replacement": (
                        "[SI.GFE](factortester://product/"
                        "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
                    ),
                    "count": 1,
                },
                {
                    "field": "body", "source": "RunSpec",
                    "replacement": "`RunSpec`", "count": 1,
                },
            ],
        }],
    }

    result = migrate_component_semantics(
        package_root=package, branch_id="main",
        scope=SimpleNamespace(), plan=plan,
    )
    saved = load_snapshot(package_root=package, branch_id="main")

    assert result["changed_component_count"] == 1
    assert result["reviewed_component_count"] == 2
    finding = next(
        item for item in saved["components"]
        if item["component_id"] == "finding"
    )
    assert "[SI.GFE](factortester://product/" in finding["body"]
    assert "`RunSpec`" in finding["body"]
    bindings = [
        item for item in saved["bindings"]
        if item["component_id"] == "finding"
    ]
    assert {item["binding_id"] for item in bindings} == {
        "workflow-checkpoint", "reference-product",
    }


def test_replacement_does_not_rewrite_a_link_created_by_an_earlier_rule() -> None:
    linked, count = _replace_unformatted(
        "比较 SgCPSVol 与 SgCPS",
        "SgCPSVol", "[SgCPSVol](factortester://factor/one)",
    )
    result, second_count = _replace_unformatted(
        linked, "SgCPS", "[SgCPS](factortester://factor/two)",
    )

    assert count == second_count == 1
    assert result == (
        "[SgCPSVol](factortester://factor/one) 与 "
        "[SgCPS](factortester://factor/two)"
    ).join(("比较 ", ""))


def test_token_replacement_does_not_match_a_longer_identifier() -> None:
    result, count = _replace_unformatted(
        "VW 与 VWAP，CA 与 canonical",
        "VW", "[VW](factortester://factor/vw)", match_mode="token",
    )
    result, second_count = _replace_unformatted(
        result, "CA", "`CA`", match_mode="token",
    )

    assert count == second_count == 1
    assert result == (
        "[VW](factortester://factor/vw) 与 VWAP，"
        "`CA` 与 canonical"
    )


def test_formatted_exact_replaces_reviewed_code_with_a_typed_link() -> None:
    result, count = _replace_unformatted(
        "已将 `MmOvernightTrend` 改名",
        "`MmOvernightTrend`",
        "[MmOvernightTrend](factortester://factor/historical)",
        match_mode="formatted_exact",
    )

    assert count == 1
    assert result == (
        "已将 [MmOvernightTrend]"
        "(factortester://factor/historical) 改名"
    )


def test_formatted_exact_can_merge_split_code_spans() -> None:
    result, count = _replace_unformatted(
        "[TrMomentum]=`CLOSE`/`CLOSE`.shift(N)-1",
        "`CLOSE`/`CLOSE`.shift(N)-1",
        "`CLOSE / CLOSE.shift(N) - 1`",
        match_mode="formatted_exact",
    )

    assert count == 1
    assert result == "[TrMomentum]=`CLOSE / CLOSE.shift(N) - 1`"


def test_formatted_exact_still_cannot_change_visible_report_prose(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="假设登记", parent_id=None,
        body="比较 `MmTrend`", content=None, display_kind="",
    )
    snapshot = load_snapshot(package_root=package, branch_id="main")
    import hashlib
    identities = sorted(item["component_id"] for item in snapshot["components"])
    digest = hashlib.sha256(
        json.dumps(
            identities, ensure_ascii=False, separators=(",", ":"),
        ).encode()
    ).hexdigest()
    monkeypatch.setattr(
        "tools.cli.release.research_reporting.maintenance."
        "component_semantics.preflight_component",
        lambda **_: [],
    )
    plan = {
        "schema_version": 1,
        "migration_id": "semantic-v1",
        "reviewed_component_count": 1,
        "reviewed_component_digest": digest,
        "changes": [{
            "component_id": "chapter",
            "replacements": [{
                "field": "body",
                "source": "`MmTrend`",
                "replacement": "`MmTrendRenamed`",
                "match_mode": "formatted_exact",
                "count": 1,
            }],
        }],
    }

    try:
        prepare_component_semantics(
            package_root=package,
            branch_id="main",
            scope=SimpleNamespace(),
            plan=plan,
        )
    except ValueError as error:
        assert "changed report prose" in str(error)
    else:
        raise AssertionError("visible prose change was not rejected")


def test_prepare_component_migration_has_no_source_tree_side_effect(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="假设登记", parent_id=None,
        body="使用 RunSpec", content=None, display_kind="",
    )
    snapshot = load_snapshot(package_root=package, branch_id="main")
    import hashlib, json
    identities = sorted(item["component_id"] for item in snapshot["components"])
    digest = hashlib.sha256(
        json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(
        "tools.cli.release.research_reporting.maintenance."
        "component_semantics.preflight_component",
        lambda **_: [],
    )
    plan = {
        "schema_version": 1, "migration_id": "semantic-v1",
        "reviewed_component_count": 1,
        "reviewed_component_digest": digest,
        "changes": [{
            "component_id": "chapter",
            "replacements": [{
                "field": "body", "source": "RunSpec",
                "replacement": "`RunSpec`", "count": 1,
            }],
        }],
    }

    prepared = prepare_component_semantics(
        package_root=package, branch_id="main",
        scope=SimpleNamespace(), plan=plan,
    )

    assert prepared["generation_after"] == snapshot["head"]["generation"] + 1
    assert prepared["operations"][0]["body"] == "使用 `RunSpec`"
    assert load_snapshot(
        package_root=package, branch_id="main",
    )["head"] == snapshot["head"]


def test_semantic_migration_command_records_plan_and_receipt(
    tmp_path: Path, monkeypatch,
) -> None:
    package = tmp_path / "research" / "wp"
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({
        "schema_version": 1, "migration_id": "semantic-v1",
        "reviewed_component_count": 1,
        "reviewed_component_digest": "digest",
        "changes": [{"component_id": "entry", "replacements": []}],
    }))
    scope = SimpleNamespace(package_root=package)
    monkeypatch.setattr(
        "tools.cli.commands.research_report_semantic_migration."
        "load_profile_root", lambda _: tmp_path,
    )
    monkeypatch.setattr(
        "tools.cli.commands.research_report_semantic_migration."
        "resolve_branch_report_scope", lambda **_: scope,
    )
    monkeypatch.setattr(
        "tools.cli.commands.research_report_semantic_migration."
        "migrate_component_semantics",
        lambda **_: {
            "migration_id": "semantic-v1",
            "generation_before": 1, "generation_after": 2,
        },
    )
    monkeypatch.setattr(
        "tools.cli.commands.research_report_semantic_migration."
        "export_branch_report", lambda **_: {
            "path": package / "REPORT.md", "changed": True,
            "content_hash": "f" * 64,
        },
    )
    monkeypatch.setattr(
        "tools.cli.commands.research_report_semantic_migration."
        "commit_branch_authoring", lambda *_args, **_kwargs: {"commit": "abc"},
    )

    result = CliRunner().invoke(migrate_component_semantics_command, [
        "--profile", "maxa", "--work-package-id", "wp",
        "--branch-id", "main", "--plan-file", str(plan_file), "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert Path(payload["plan"]).is_file()
    assert Path(payload["receipt"]).is_file()
    assert len(payload["plan_sha256"]) == 64
    assert payload["export"]["changed"] is True
    assert payload["git"] == {"commit": "abc"}


def test_canonical_plan_accepts_equivalent_json_formatting(tmp_path: Path) -> None:
    path = tmp_path / "semantic.plan.json"
    plan = {"schema_version": 1, "changes": [], "migration_id": "semantic"}
    path.write_text(
        '{"migration_id":"semantic","changes":[],"schema_version":1}',
        encoding="utf-8",
    )
    encoded = (
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()

    _accept_or_reject_existing_plan(path, plan, encoded)

    assert path.read_bytes() == encoded


def test_canonical_plan_rejects_different_json_content(tmp_path: Path) -> None:
    path = tmp_path / "semantic.plan.json"
    path.write_text(
        '{"migration_id":"other","changes":[],"schema_version":1}',
        encoding="utf-8",
    )
    plan = {"schema_version": 1, "changes": [], "migration_id": "semantic"}
    encoded = (
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()

    try:
        _accept_or_reject_existing_plan(path, plan, encoded)
    except click.ClickException as error:
        assert "different content" in str(error)
    else:
        raise AssertionError("different migration plan was not rejected")
