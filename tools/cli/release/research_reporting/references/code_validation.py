"""Location-aware validation for report code markup."""

from __future__ import annotations

from dataclasses import dataclass
import re


_BACKTICKS = re.compile(r"(?<!\\)(`+)")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_LANGUAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+.#-]{0,31}$")


@dataclass(frozen=True)
class CodeIssue:
    offset: int
    code: str
    message: str
    rule: str
    example: str


def code_issues(value: str) -> list[CodeIssue]:
    issues: list[CodeIssue] = []
    fenced = False
    fence_marker = ""
    fence_offset = 0
    offset = 0
    for line in value.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        fence = _FENCE.match(content)
        if fence:
            marker = fence.group(1)
            if not fenced:
                language = fence.group(2).strip()
                if issue := language_issue(
                    language, offset=offset + fence.end(1),
                ):
                    issues.append(issue)
                fenced = True
                fence_marker = marker
                fence_offset = offset + fence.start(1)
            elif (
                marker[0] == fence_marker[0]
                and len(marker) >= len(fence_marker)
                and not fence.group(2).strip()
            ):
                fenced = False
                fence_marker = ""
            offset += len(line)
            continue
        if not fenced:
            issues.extend(_inline_issues(content, offset))
        offset += len(line)
    if fenced:
        issues.append(CodeIssue(
            offset=fence_offset,
            code="report.code.fence.unclosed",
            message="代码围栏未闭合",
            rule="代码围栏必须使用同类且不少于开头长度的标记闭合",
            example="```python\nsignal = close.pct_change()\n```",
        ))
    return issues


def language_issue(value: str, *, offset: int = 0) -> CodeIssue | None:
    if not value or _LANGUAGE.fullmatch(value):
        return None
    return CodeIssue(
        offset=offset,
        code="report.code.fence.language",
        message="代码围栏语言标签无效",
        rule=(
            "代码语言标签只能包含字母、数字、加号、井号、"
            "点、下划线或连字符"
        ),
        example="```python",
    )


def _inline_issues(line: str, base_offset: int) -> list[CodeIssue]:
    runs = list(_BACKTICKS.finditer(line))
    cursor = 0
    while cursor < len(runs):
        opening = runs[cursor]
        length = len(opening.group(1))
        closing = next(
            (
                index for index in range(cursor + 1, len(runs))
                if len(runs[index].group(1)) == length
            ),
            None,
        )
        if closing is None:
            return [CodeIssue(
                offset=base_offset + opening.start(),
                code="report.code.inline.invalid",
                message="行内代码反引号未闭合",
                rule="行内代码必须在同一行使用等长反引号成对包围",
                example="信号写作 `SgCCS`",
            )]
        cursor = closing + 1
    return []
