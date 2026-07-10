from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ROOT_PATTERNS = (
    re.compile(r"实际目录:\s*(?P<path>.+)$"),
    re.compile(r"workspace:\s*(?P<path>.+)$"),
    re.compile(r"resolved_root['\"]?\s*[:=]\s*['\"](?P<path>[^'\"]+)"),
)


def parse_workspace_root(text: str) -> str:
    for line in text.splitlines():
        for pattern in ROOT_PATTERNS:
            match = pattern.search(line.strip())
            if match:
                value = match.group("path").strip()
                if value and value != "默认用户目录":
                    return value
    return ""


def inspect_factor_source(root: str, factor_family: str, *, max_files: int = 8, max_lines: int = 80) -> dict[str, Any]:
    base = Path(root).expanduser()
    if not base.exists():
        raise FileNotFoundError(f"factor workspace root not found: {root}")
    hits: list[dict[str, Any]] = []
    needles = {factor_family, factor_family.lower()}
    for path in sorted(base.rglob("*.py")):
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if not any(needle.lower() in lowered for needle in needles):
            continue
        hits.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(base)),
                "summary": summarize_factor_source(text, factor_family=factor_family, max_lines=max_lines),
            }
        )
        if len(hits) >= max_files:
            break
    return {
        "workspace_root": str(base),
        "factor_family": factor_family,
        "files": hits,
        "file_count": len(hits),
    }


def summarize_factor_source(text: str, *, factor_family: str, max_lines: int) -> list[str]:
    interesting: list[str] = []
    patterns = (
        re.compile(r"^\s*class\s+"),
        re.compile(r"^\s*def\s+"),
        re.compile(r"^\s*(alias|name|description|expr|expression|formula)\s*="),
        re.compile(re.escape(factor_family), re.IGNORECASE),
        re.compile(r"rolling|rank|corr|shift|SIGNAL_ALIGN|ColumnRef|FactorFamily"),
    )
    for line in text.splitlines():
        stripped = line.rstrip()
        if any(pattern.search(stripped) for pattern in patterns):
            interesting.append(stripped[:240])
        if len(interesting) >= max_lines:
            break
    return interesting
