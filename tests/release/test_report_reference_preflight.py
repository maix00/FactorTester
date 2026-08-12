from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting.references.preflight import (
    ReportPreflightError,
    preflight_component,
)


def test_preflight_reports_reference_location_rule_and_example(
    tmp_path: Path,
) -> None:
    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            raise LookupError("classifier object path does not resolve uniquely")

    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="finding",
            kind="entry",
            title="发现",
            body=(
                "第一行\n"
                "引用 [工业硅](factortester://product/"
                "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
            ),
            content=None,
            scope=_scope(tmp_path),
            client=Client(),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["component_id"] == "finding"
    assert diagnostic["field"] == "body"
    assert diagnostic["line"] == 2
    assert diagnostic["column"] > 1
    assert diagnostic["code"] == "report.reference.authority"
    assert "精确" in diagnostic["rule"]
    assert "factortester://product/" in diagnostic["example"]


def test_preflight_locates_the_specific_rejected_reference(
    tmp_path: Path,
) -> None:
    first_ref = "Product/Futures/CNFutures/_products/SI.GFE"
    rejected_ref = "Product/Futures/CNFutures/_products/UR.CZC"
    body = (
        "[工业硅](factortester://product/"
        "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE) 与 "
        "[尿素](factortester://product/"
        "Product%2FFutures%2FCNFutures%2F_products%2FUR.CZC)"
    )

    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            if target_ref == rejected_ref:
                raise LookupError("catalog path does not exist")
            return {
                "kind": kind,
                "target_ref": first_ref,
                "object": {"entity_path": first_ref},
            }

    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="products",
            kind="entry",
            title="品种",
            body=body,
            content=None,
            scope=_scope(tmp_path),
            client=Client(),
        )

    second_url = body.rfind("factortester://product/")
    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["line"] == 1
    assert diagnostic["column"] == second_url + 1


def test_preflight_reports_invalid_latex_with_location(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="formula",
            kind="entry",
            title="公式",
            body="收益为 \\(r_{t\\)。",
            content=None,
            scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["code"] == "report.math.invalid"
    assert diagnostic["line"] == 1
    assert diagnostic["rule"]
    assert diagnostic["example"]


def test_preflight_returns_a_context_binding_for_each_valid_reference(
    tmp_path: Path,
) -> None:
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"

    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            return {
                "kind": kind,
                "target_ref": target_ref,
                "object": {"entity_path": target_ref},
            }

    bindings = preflight_component(
        component_id="finding",
        kind="entry",
        title="发现",
        body=(
            "[工业硅](factortester://product/"
            "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
        ),
        content=None,
        scope=_scope(tmp_path),
        client=Client(),
    )

    assert len(bindings) == 1
    assert bindings[0]["kind"] == "product"
    assert bindings[0]["target_ref"] == target_ref
    assert bindings[0]["data"]["entity_path"] == target_ref


def test_preflight_accepts_a_typed_direct_trial_plan_link(
    tmp_path: Path,
) -> None:
    digest = "b" * 64
    target_ref = "trial-plan:sha256:" + digest

    class Client:
        def get_direct_trial_plan(self, requested_ref):
            assert requested_ref == target_ref
            return {
                "binding_origin": "agent_direct",
                "trial_plan_ref": target_ref,
                "trial_plan_hash": digest,
                "trial_plan_id": "direct-plan",
                "trial_plan_version": 1,
                "title_zh": "直接试验计划",
            }

    bindings = preflight_component(
        component_id="direct-trial",
        kind="entry",
        title="直接试验",
        body=(
            "[直接试验计划](factortester://trial_plan/"
            f"trial-plan%3Asha256%3A{digest})"
        ),
        content=None,
        scope=_scope(tmp_path),
        client=Client(),
    )

    assert bindings[0]["kind"] == "trial_plan"
    assert bindings[0]["target_ref"] == target_ref
    assert bindings[0]["data"]["authority_scope"] == "direct_registry"


def test_preflight_does_not_infer_an_object_from_plain_text(tmp_path: Path) -> None:
    assert preflight_component(
        component_id="finding",
        kind="entry",
        title="发现",
        body="SI.GFE 与 MaxA 保持为 Agent 尚未声明的文本",
        content=None,
        scope=_scope(tmp_path),
    ) == []


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            "证据对象是 evidence:data_contract:sha256:" + "a" * 64,
            "report.reference.raw_object",
        ),
        (
            "证据对象是 `evidence:data_contract:sha256:" + "a" * 64 + "`",
            "report.reference.raw_object",
        ),
        (
            "证据哈希为 sha256:" + "b" * 64,
            "report.hash.reader_facing",
        ),
        (
            "冻结摘要为 " + "c" * 64,
            "report.hash.reader_facing",
        ),
    ],
)
def test_preflight_rejects_reader_facing_object_refs_and_hashes(
    tmp_path: Path,
    body: str,
    code: str,
) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="finding",
            kind="entry",
            title="发现",
            body=body,
            content=None,
            scope=_scope(tmp_path),
        )

    issue = captured.value.diagnostics[0]
    assert issue["code"] == code
    assert issue["field"] == "body"
    assert "factortester://" in issue["example"]


def test_preflight_accepts_typed_evidence_link_but_ignores_code_fence_hashes(
    tmp_path: Path,
) -> None:
    target_ref = "evidence:data_contract:sha256:" + "a" * 64

    class Client:
        def get_research_evidence(self, requested_ref):
            assert requested_ref == target_ref
            return {
                "evidence_ref": target_ref,
                "evidence_kind": "data_availability",
            }

    body = (
        "结论见 [数据契约证据](factortester://evidence/"
        "evidence%3Adata_contract%3Asha256%3A" + "a" * 64 + ")\n\n"
        "```text\nsha256:" + "b" * 64 + "\n```"
    )

    bindings = preflight_component(
        component_id="finding",
        kind="entry",
        title="发现",
        body=body,
        content=None,
        scope=_scope(tmp_path),
        client=Client(),
    )

    assert [item["target_ref"] for item in bindings] == [target_ref]


def test_preflight_applies_raw_object_gate_to_list_items(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="findings",
            kind="list",
            title="",
            body="",
            content={
                "items": [{
                    "text": "任务 job:backtest-123",
                }],
            },
            scope=_scope(tmp_path),
        )

    issue = captured.value.diagnostics[0]
    assert issue["code"] == "report.reference.raw_object"
    assert issue["field"] == "content.items[0].text"


def _scope(tmp_path: Path):
    return SimpleNamespace(
        client_root=tmp_path / "client",
        profile_id="maxa",
        profile={},
        package_root=tmp_path / "workspace" / "research" / "wp",
    )
