from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting.references.preflight import (
    ReportPreflightError,
    preflight_component,
)


def _scope(tmp_path: Path) -> SimpleNamespace:
    package = tmp_path / "research" / "wp"
    package.mkdir(parents=True)
    return SimpleNamespace(
        client_root=tmp_path / "client",
        package_root=package,
        profile_id="maxa",
        profile={},
    )


def test_preflight_accepts_an_existing_work_package_file(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    source = scope.package_root / "assets" / "audit.md"
    source.parent.mkdir()
    source.write_text("# 审计\n", encoding="utf-8")

    assert preflight_component(
        component_id="finding",
        kind="entry",
        title="结论",
        body="详见 [审计](assets/audit.md)",
        content=None,
        scope=scope,
    ) == []


def test_preflight_accepts_work_package_research_method_memory(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    method = (
        scope.package_root
        / "research-methods"
        / "references"
        / "per-period-fee-attribution.md"
    )
    method.parent.mkdir(parents=True)
    method.write_text("# 逐期手续费归因\n", encoding="utf-8")

    assert preflight_component(
        component_id="method-rationale",
        kind="entry",
        title="方法选择",
        body=(
            "采用[逐期手续费归因]"
            "(research-methods/references/per-period-fee-attribution.md)，"
            "因为按日聚合会掩盖分钟级费用归因。"
        ),
        content=None,
        scope=scope,
    ) == []


def test_preflight_rejects_a_missing_work_package_file(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="finding",
            kind="entry",
            title="结论",
            body="第一行\n详见 [审计](assets/missing.md)",
            content=None,
            scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["code"] == "report.markdown.file.missing"
    assert diagnostic["line"] == 2
    assert diagnostic["field"] == "body"
    assert diagnostic["rule"]
    assert diagnostic["example"]


def test_preflight_rejects_a_work_package_escape(tmp_path: Path) -> None:
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="finding",
            kind="entry",
            title="结论",
            body="详见 [其他文件](../secret.md)",
            content=None,
            scope=_scope(tmp_path),
        )

    assert captured.value.diagnostics[0]["code"] == "report.markdown.file.unsafe"


def test_preflight_does_not_fetch_external_links(tmp_path: Path) -> None:
    assert preflight_component(
        component_id="source",
        kind="entry",
        title="来源",
        body="来源见 [交易所公告](https://example.com/notice)",
        content=None,
        scope=_scope(tmp_path),
    ) == []
