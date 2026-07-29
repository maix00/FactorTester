"""Location-aware validation for portable Markdown links."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit


_LINK_START = re.compile(r"(?<!\\)!?\[([^\]\n]*)\]\(")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_RULE = (
    "链接必须写为 [说明](https://example.com/path) "
    "或 [说明](relative/path)"
)
_EXAMPLE = "来源见 [交易所公告](https://example.com/notice)"


@dataclass(frozen=True)
class MarkdownIssue:
    offset: int
    code: str
    message: str
    rule: str = _RULE
    example: str = _EXAMPLE


def markdown_link_issues(value: str) -> list[MarkdownIssue]:
    """Validate authored links without interpreting surrounding prose."""
    issues: list[MarkdownIssue] = []
    for match in _LINK_START.finditer(value):
        if _inside_code(value, match.start()):
            continue
        if not match.group(1).strip():
            issues.append(_issue(match.start(), "Markdown 链接说明不能为空"))
            continue
        end = value.find(")", match.end())
        if end < 0:
            issues.append(_issue(match.start(), "Markdown 链接缺少右括号"))
            continue
        target = value[match.end():end]
        if not target:
            issues.append(_issue(match.end(), "Markdown 链接目标不能为空"))
        elif any(character.isspace() for character in target):
            issues.append(_issue(match.end(), "Markdown 链接目标不能包含空白字符"))
        elif "(" in target:
            issues.append(_issue(match.end(), "Markdown 链接目标不能包含未编码的括号"))
        elif not _supported_target(target):
            issues.append(_issue(match.end(), "Markdown 链接协议不受支持"))
    return issues


def _supported_target(target: str) -> bool:
    if target.startswith("factortester://"):
        return True
    parsed = urlsplit(target)
    scheme = parsed.scheme
    if scheme:
        return (
            scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    return not _SCHEME.match(target) and not target.startswith("//")


def _inside_code(value: str, offset: int) -> bool:
    line_start = value.rfind("\n", 0, offset) + 1
    before = value[line_start:offset]
    return before.count("`") % 2 == 1


def _issue(offset: int, message: str) -> MarkdownIssue:
    return MarkdownIssue(
        offset=offset,
        code="report.markdown.link.invalid",
        message=message,
    )
