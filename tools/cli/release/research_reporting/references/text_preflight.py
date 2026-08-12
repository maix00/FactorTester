"""Validate one report text field before authority resolution."""

from __future__ import annotations

from typing import Any

from ..authoring.inline_links import validate_inline_links
from ..authoring.tree_rich_text import validate_rich_text
from .code_masking import mask_code_markup
from .code_validation import code_issues
from .component_text import ComponentText
from .diagnostics import diagnostic
from .markdown_validation import markdown_link_issues
from .math_validation import formula_issues, raw_formula_issues
from .object_identity_validation import reader_facing_identity_issues
from .technical_identifier_validation import unformatted_underscore_issues


_MATH_RULE = (
    r"行内使用 \(...\)，行间使用 \[...\] 或 $$...$$，花括号必须配对"
)
_MATH_EXAMPLE = r"收益为 \(r_t = P_t / P_{t-1} - 1\)"


def preflight_text(
    *, component_id: str, text: ComponentText,
) -> tuple[str, list[dict[str, Any]]]:
    code = (
        code_issues(text.value)
        if text.mode in {"rich", "inline"}
        else []
    )
    if code:
        return text.value, _issue_diagnostics(
            component_id=component_id, text=text, issues=code,
        )
    semantic_value = (
        mask_code_markup(text.value)
        if text.mode in {"rich", "inline"}
        else text.value
    )
    markdown = (
        markdown_link_issues(semantic_value)
        if text.mode in {"rich", "inline"}
        else []
    )
    if markdown:
        return semantic_value, _issue_diagnostics(
            component_id=component_id, text=text, issues=markdown,
        )
    if text.mode in {"rich", "inline"}:
        identities = reader_facing_identity_issues(text.value)
        if identities:
            return semantic_value, _issue_diagnostics(
                component_id=component_id, text=text, issues=identities,
            )
    math = (
        raw_formula_issues(text.value)
        if text.mode == "latex"
        else formula_issues(semantic_value)
    )
    if math:
        return semantic_value, [
            diagnostic(
                component_id=component_id, field=text.field,
                value=text.value, offset=issue.offset,
                code="report.math.invalid", message=issue.message,
                rule=_MATH_RULE, example=_MATH_EXAMPLE,
            )
            for issue in math
        ]
    if text.mode in {"rich", "inline"}:
        technical = unformatted_underscore_issues(semantic_value)
        if technical:
            return semantic_value, [
                diagnostic(
                    component_id=component_id, field=text.field,
                    value=text.value, offset=issue.offset,
                    code="report.technical_identifier.unformatted",
                    message=(
                        f"技术标识 {issue.value} 未放入代码或数学环境"
                    ),
                    rule=(
                        "含下划线的技术标识必须使用 `...`、"
                        r"\(...\) 或行间数学环境"
                    ),
                    example="使用 `cs_ordinal_rank(mask, ascending)` 排名",
                )
                for issue in technical
            ]
    try:
        if text.mode == "rich":
            validate_rich_text(semantic_value, field=text.field)
        elif text.mode == "inline":
            validate_inline_links(semantic_value, field=text.field)
    except ValueError as error:
        return semantic_value, [diagnostic(
            component_id=component_id, field=text.field,
            value=text.value, offset=_problem_offset(text.value),
            code="report.markdown.invalid", message=str(error),
            rule="使用闭合且规范的 Markdown 链接、代码和公式语法",
            example="结论见 [证据](https://example.com/evidence)",
        )]
    return semantic_value, []


def _issue_diagnostics(
    *, component_id: str, text: ComponentText, issues: list[Any],
) -> list[dict[str, Any]]:
    return [
        diagnostic(
            component_id=component_id, field=text.field,
            value=text.value, offset=issue.offset,
            code=issue.code, message=issue.message,
            rule=issue.rule, example=issue.example,
        )
        for issue in issues
    ]


def _problem_offset(value: str) -> int:
    candidates = [
        offset
        for token in ("factortester://", "```", "~~~", r"\(", r"\[", "$$")
        if (offset := value.find(token)) >= 0
    ]
    return min(candidates) if candidates else 0
