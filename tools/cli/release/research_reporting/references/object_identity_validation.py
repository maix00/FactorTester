"""Reject reader-facing object identities that should be typed links."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import quote

from ..authoring.inline_links import MARKDOWN_LINK_PATTERN


_MARKDOWN_LINK = re.compile(MARKDOWN_LINK_PATTERN)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_RAW_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_/-])"
    r"(?P<target>"
    r"(?:factor-family|factor-set|profile-revision|trial-plan|runspec|"
    r"evidence|task|job|run|profile|"
    r"factor|requirement)"
    r":[A-Za-z0-9._~:/|$@+\-\[\]]{1,2048}"
    r")"
)
_READER_HASH = re.compile(
    r"(?<![0-9A-Fa-f])(?:sha256:)?(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{40})"
    r"(?![0-9A-Fa-f])"
)
_REFERENCE_KIND = {
    "evidence": ("evidence", "证据"),
    "task": ("task", "任务"),
    "job": ("job", "测试任务"),
    "run": ("run", "运行"),
    "runspec": ("run_spec", "运行配置"),
    "trial-plan": ("trial_plan", "试验计划"),
    "profile": ("profile", "Profile"),
    "profile-revision": ("profile_revision", "Profile 版本"),
    "factor": ("factor", "因子"),
    "factor-family": ("factor", "因子家族"),
    "factor-set": ("factor", "因子集合"),
}


@dataclass(frozen=True)
class ObjectIdentityIssue:
    offset: int
    code: str
    message: str
    rule: str
    example: str


def reader_facing_identity_issues(value: str) -> list[ObjectIdentityIssue]:
    """Find raw stable references and hashes outside fenced code and link URLs."""
    visible = list(value)
    _mask_fenced_code(visible, value)
    for match in _MARKDOWN_LINK.finditer(value):
        _blank(visible, match.start(2), match.end(2))
    candidate = "".join(visible)

    issues: list[ObjectIdentityIssue] = []
    consumed: list[tuple[int, int]] = []
    for match in _RAW_REFERENCE.finditer(candidate):
        target = match.group("target")
        prefix = target.split(":", 1)[0]
        kind, title = _REFERENCE_KIND[prefix]
        issues.append(ObjectIdentityIssue(
            offset=match.start("target"),
            code="report.reference.raw_object",
            message=f"稳定对象引用 {target} 不能作为普通正文或行内代码显示",
            rule=(
                "报告提到已有领域对象时必须使用带短标题的类型化 Markdown "
                "超链接；对象哈希只保留在链接目标和结构化 binding 中"
            ),
            example=(
                f"[{title}短标题](factortester://{kind}/"
                f"{quote(target, safe='')})"
            ),
        ))
        consumed.append(match.span("target"))

    for match in _READER_HASH.finditer(candidate):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        issues.append(ObjectIdentityIssue(
            offset=match.start(),
            code="report.hash.reader_facing",
            message="裸哈希不能作为读者可见的研究报告内容",
            rule=(
                "先从对象所属 CLI 响应取得完整 target_ref，"
                "再使用类型化链接；"
                "无法确认对象类型时不得用哈希代替研究语义"
            ),
            example=(
                "[证据短标题](factortester://evidence/"
                "<percent-encoded-evidence_ref>)"
            ),
        ))
    return sorted(issues, key=lambda item: item.offset)


def _mask_fenced_code(masked: list[str], value: str) -> None:
    fenced = False
    marker = ""
    offset = 0
    for line in value.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        fence = _FENCE.match(content)
        if fence:
            current = fence.group(1)
            closes = (
                fenced
                and current[0] == marker[0]
                and len(current) >= len(marker)
                and not fence.group(2).strip()
            )
            if not fenced:
                fenced = True
                marker = current
            _blank(masked, offset, offset + len(content))
            if closes:
                fenced = False
                marker = ""
        elif fenced:
            _blank(masked, offset, offset + len(content))
        offset += len(line)


def _blank(value: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if value[index] not in "\r\n":
            value[index] = " "
