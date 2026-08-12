"""Bounded structural validation for report LaTex fragments."""

from __future__ import annotations

from dataclasses import dataclass
import re


_FORMULA = re.compile(
    r"\\\((.*?)\\\)|\\\[(.*?)\\\]|\$\$(.*?)\$\$",
    re.DOTALL,
)


@dataclass(frozen=True)
class MathIssue:
    offset: int
    message: str


def formula_issues(value: str) -> list[MathIssue]:
    issues = _delimiter_issues(value)
    if issues:
        return issues
    result: list[MathIssue] = []
    for match in _FORMULA.finditer(value):
        formula = next(group for group in match.groups() if group is not None)
        content_offset = match.start() + (
            2 if match.group(1) is not None or match.group(2) is not None else 2
        )
        result.extend(_brace_issues(formula, content_offset))
    return result


def raw_formula_issues(value: str) -> list[MathIssue]:
    return _brace_issues(value, 0)


def _delimiter_issues(value: str) -> list[MathIssue]:
    for opening, closing, label in (
        (r"\(", r"\)", "行内公式"),
        (r"\[", r"\]", "行间公式"),
    ):
        if value.count(opening) != value.count(closing):
            offset = value.find(opening)
            if offset < 0:
                offset = value.find(closing)
            return [MathIssue(max(offset, 0), f"{label}分隔符不配对")]
    if value.count("$$") % 2:
        return [MathIssue(max(value.rfind("$$"), 0), "行间公式 $$ 分隔符不配对")]
    return []

def _brace_issues(value: str, base_offset: int) -> list[MathIssue]:
    stack: list[int] = []
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
        elif character == "{":
            stack.append(index)
        elif character == "}":
            if not stack:
                return [MathIssue(base_offset + index, "LaTex 出现多余的右花括号")]
            stack.pop()
    if stack:
        return [MathIssue(base_offset + stack[-1], "LaTex 花括号未闭合")]
    return []
