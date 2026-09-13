"""Validate report-local Markdown targets inside the current Work Package."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit


_LINK = re.compile(r"(?<!\\)!?\[[^\]\n]+\]\(([^()\s]+)\)")


@dataclass(frozen=True)
class SourceLinkIssue:
    offset: int
    code: str
    message: str
    rule: str
    example: str


def source_link_issues(value: str, *, package_root: Path, branch_root: Path | None = None) -> list[SourceLinkIssue]:
    """Check only relative files; web and typed links have separate authorities."""
    issues: list[SourceLinkIssue] = []
    root = package_root.resolve()
    roots = [root]
    if branch_root is not None:
        branch = branch_root.resolve()
        if not branch.is_relative_to(root):
            raise ValueError('report branch escapes Work Package')
        roots.insert(0, branch)
    for match in _LINK.finditer(value):
        target = match.group(1)
        if urlsplit(target).scheme or target.startswith("#"):
            continue
        path = unquote(target.split("#", 1)[0])
        if not _safe_relative(path):
            issues.append(_issue(
                match.start(1), "report.markdown.file.unsafe",
                "研究文件链接必须位于当前 Work Package 内",
            ))
            continue
        resolved = [(base / PurePosixPath(path)).resolve() for base in roots]
        if not any(candidate.is_relative_to(root) and candidate.is_file() for candidate in resolved):
            issues.append(_issue(
                match.start(1), "report.markdown.file.missing",
                "研究文件链接目标不存在或不是文件",
            ))
    return issues


def _safe_relative(value: str) -> bool:
    if not value or value.startswith(("/", "~")) or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(
        part not in {"", ".", ".."} for part in path.parts
    )


def _issue(offset: int, code: str, message: str) -> SourceLinkIssue:
    return SourceLinkIssue(
        offset=offset,
        code=code,
        message=message,
        rule="相对文件链接必须指向当前 Work Package 内已存在的文件",
        example="[数据审计](assets/data-audits/coverage.md)",
    )
