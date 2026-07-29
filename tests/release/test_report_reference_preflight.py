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


def test_preflight_does_not_infer_an_object_from_plain_text(tmp_path: Path) -> None:
    assert preflight_component(
        component_id="finding",
        kind="entry",
        title="发现",
        body="SI.GFE 与 MaxA 保持为 Agent 尚未声明的文本",
        content=None,
        scope=_scope(tmp_path),
    ) == []


def _scope(tmp_path: Path):
    return SimpleNamespace(
        client_root=tmp_path / "client",
        profile_id="maxa",
        profile={},
        package_root=tmp_path / "workspace" / "research" / "wp",
    )
