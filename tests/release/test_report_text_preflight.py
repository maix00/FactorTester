from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting.references.preflight import (
    ReportPreflightError,
    preflight_component,
)


def test_reports_malformed_ordinary_markdown_link(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="sources", kind="entry", title="来源",
            body="第一行\n来源见 [交易所公告](https://example.com/notice",
            content=None, scope=_scope(tmp_path),
        )

    assert captured.value.diagnostics[0] == {
        "component_id": "sources",
        "field": "body",
        "line": 2,
        "column": 5,
        "code": "report.markdown.link.invalid",
        "message": "Markdown 链接缺少右括号",
        "rule": "链接必须写为 [说明](https://example.com/path) 或 [说明](relative/path)",
        "example": "来源见 [交易所公告](https://example.com/notice)",
    }


@pytest.mark.parametrize(
    "target",
    [
        "https://",
        "https://user:secret@example.com/notice",
        "file:///tmp/notice.md",
    ],
)
def test_rejects_unsafe_or_incomplete_web_links(
    tmp_path: Path, target: str,
) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="sources", kind="entry", title="来源",
            body=f"来源见 [公告]({target})",
            content=None, scope=_scope(tmp_path),
        )

    assert captured.value.diagnostics[0]["code"] == "report.markdown.link.invalid"


def test_reports_unclosed_inline_code_with_exact_location(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="method", kind="entry", title="方法",
            body="第一行\n使用 `SgCCS 作为信号",
            content=None, scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["component_id"] == "method"
    assert diagnostic["field"] == "body"
    assert diagnostic["line"] == 2
    assert diagnostic["column"] == 4
    assert diagnostic["code"] == "report.code.inline.invalid"
    assert diagnostic["rule"] == "行内代码必须在同一行使用等长反引号成对包围"
    assert diagnostic["example"] == "信号写作 `SgCCS`"


def test_reports_unclosed_fenced_code_at_the_opening(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="implementation", kind="entry", title="实现",
            body="说明\n```python\nsignal = close.pct_change()\n",
            content=None, scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["field"] == "body"
    assert diagnostic["line"] == 2
    assert diagnostic["column"] == 1
    assert diagnostic["code"] == "report.code.fence.unclosed"
    assert diagnostic["rule"] == "代码围栏必须使用同类且不少于开头长度的标记闭合"
    assert diagnostic["example"] == "```python\nsignal = close.pct_change()\n```"


def test_reports_invalid_fenced_code_language_label(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="implementation", kind="entry", title="实现",
            body="```python script\nsignal = close.pct_change()\n```",
            content=None, scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["line"] == 1
    assert diagnostic["column"] == 4
    assert diagnostic["code"] == "report.code.fence.language"
    assert diagnostic["rule"] == (
        "代码语言标签只能包含字母、数字、加号、井号、点、下划线或连字符"
    )
    assert diagnostic["example"] == "```python"


def test_reports_invalid_code_component_language(tmp_path: Path) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="source", kind="code", title="源码", body="",
            content={"language": "python script", "code": "signal = close"},
            scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["field"] == "content.language"
    assert diagnostic["line"] == 1
    assert diagnostic["column"] == 1
    assert diagnostic["code"] == "report.code.fence.language"


def test_does_not_parse_formula_delimiters_inside_code(tmp_path: Path) -> None:
    assert preflight_component(
        component_id="syntax", kind="entry", title="语法示例",
        body=(
            r"行内字面量 `\\(not_formula`"
            "\n```text\n"
            r"\\[also_not_formula"
            "\n```"
        ),
        content=None, scope=_scope(tmp_path),
    ) == []


def test_rejects_bare_underscore_identifiers_but_accepts_code_and_math(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="rank-policy", kind="entry", title="排名规则",
            body=(
                "按 cs_rank 筛选，再调用 "
                "cs_ordinal_rank(mask, ascending)"
            ),
            content=None, scope=_scope(tmp_path),
        )

    diagnostics = captured.value.diagnostics
    assert [item["code"] for item in diagnostics] == [
        "report.technical_identifier.unformatted",
        "report.technical_identifier.unformatted",
    ]
    assert [item["line"] for item in diagnostics] == [1, 1]
    assert [item["column"] for item in diagnostics] == [3, 18]

    assert preflight_component(
        component_id="rank-policy", kind="entry", title="排名规则",
        body=(
            r"按 `cs_rank` 筛选，再调用 "
            r"`cs_ordinal_rank(mask, ascending)`；数学量写作 \(r_t\)"
        ),
        content=None, scope=_scope(tmp_path),
    ) == []


def test_special_section_labels_cannot_be_attached_to_ordinary_entries(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReportPreflightError) as captured:
        preflight_component(
            component_id="grill", kind="entry", title="Grill 决议",
            body="已确认边界", content=None,
            display_kind="grill_resolution", scope=_scope(tmp_path),
        )

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic["code"] == "report.display_kind.kind_mismatch"
    assert diagnostic["field"] == "display_kind"
    assert diagnostic["rule"] == "特殊小节标签只能与 kind=special 一起提交"


def _scope(tmp_path: Path):
    return SimpleNamespace(
        client_root=tmp_path / "client",
        profile_id="maxa",
        profile={},
        package_root=tmp_path / "workspace" / "research" / "wp",
    )
