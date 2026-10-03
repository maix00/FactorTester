"""Preflight explicit links and rich text before publishing a report node."""

from __future__ import annotations

import hashlib
from typing import Any

from ..authoring.declared_links import declared_inline_links
from ..authoring.special_kinds import (
    AGENT_SPECIAL_SECTION_DISPLAY_KINDS,
)
from .authority import validate_declared_reference
from .code_validation import language_issue
from .component_text import component_texts
from .diagnostics import ReportPreflightError, diagnostic
from .source_links import source_link_issues
from .text_preflight import preflight_text


_REFERENCE_RULE = (
    "Agent 必须手写类型和精确 target_ref；CLI 只校验，不补全或改写"
)
_REFERENCE_EXAMPLE = (
    "[工业硅](factortester://product/"
    "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
)
def preflight_component(
    *,
    component_id: str,
    kind: str,
    title: str,
    body: str,
    content: Any,
    display_kind: str = "",
    scope: Any,
    client: Any = None,
    report_components: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if (
        not isinstance(display_kind, str)
        or len(display_kind.encode("utf-8")) > 128
        or (kind == "special" and not display_kind.strip())
    ):
        diagnostics.append(diagnostic(
            component_id=component_id, field="display_kind",
            value=str(display_kind), offset=0,
            code="report.display_kind.invalid",
            message="特殊小节需要有效且有界的 display_kind",
            rule="display_kind 必须是至多 128 字节的字符串；special 不得为空",
            example="finding",
        ))
    if (
        display_kind in AGENT_SPECIAL_SECTION_DISPLAY_KINDS
        and kind != "special"
    ):
        diagnostics.append(diagnostic(
            component_id=component_id, field="display_kind",
            value=display_kind, offset=0,
            code="report.display_kind.kind_mismatch",
            message="特殊小节标签不能附着在普通报告组件上",
            rule="特殊小节标签只能与 kind=special 一起提交",
            example=(
                "--kind special --display-kind grill_resolution"
            ),
        ))
    if kind == "code" and isinstance(content, dict):
        language = str(content.get("language") or "")
        if issue := language_issue(language):
            diagnostics.append(diagnostic(
                component_id=component_id, field="content.language",
                value=language, offset=issue.offset,
                code=issue.code, message=issue.message,
                rule=issue.rule, example=issue.example,
            ))
    for text in component_texts(
        kind=kind, title=title, body=body, content=content,
    ):
        semantic_value, text_diagnostics = preflight_text(
            component_id=component_id, text=text,
        )
        diagnostics += text_diagnostics
        if text_diagnostics:
            continue
        local_links = source_link_issues(
            semantic_value, package_root=scope.package_root,
            branch_root=(scope.package_root / 'branches' / scope.branch_id)
                if getattr(scope, 'branch_id', '') else None,
        )
        if local_links:
            diagnostics += [
                diagnostic(
                    component_id=component_id, field=text.field,
                    value=text.value, offset=issue.offset,
                    code=issue.code, message=issue.message,
                    rule=issue.rule, example=issue.example,
                )
                for issue in local_links
            ]
            continue
        for reference in declared_inline_links(semantic_value, field=text.field):
            key = (reference.kind, reference.target_ref)
            if key in seen:
                continue
            try:
                authority_options: dict[str, Any] = {
                    "reference": reference,
                    "scope": scope,
                    "client": client,
                }
                if reference.kind == 'report_section' and report_components is not None:
                    authority_options['report_components'] = report_components
                result = validate_declared_reference(**authority_options)
            except (
                KeyError, LookupError, OSError, RuntimeError, ValueError,
            ) as error:
                diagnostics.append(diagnostic(
                    component_id=component_id, field=text.field,
                    value=text.value,
                    offset=reference.url_start,
                    code="report.reference.authority", message=str(error),
                    rule=_REFERENCE_RULE, example=_REFERENCE_EXAMPLE,
                ))
                continue
            seen.add(key)
            validated.append(_binding(component_id, result))
    if diagnostics:
        raise ReportPreflightError(diagnostics)
    return validated


def _binding(component_id: str, value: dict[str, Any]) -> dict[str, Any]:
    identity = "\x1f".join((
        component_id, str(value["kind"]), str(value["target_ref"]),
    ))
    digest = hashlib.sha256(identity.encode()).hexdigest()[:40]
    return {
        "binding_id": f"reference-{digest}",
        "kind": value["kind"],
        "target_ref": value["target_ref"],
        "label": value["label"],
        "data": value["data"],
    }
