"""Inline-code policy for technical tokens embedded in Chinese report prose."""

from __future__ import annotations

import re

from .inline_links import MARKDOWN_LINK_PATTERN

_HAN = re.compile(r"[\u3400-\u9fff]")
_MARKDOWN_LINK = re.compile(MARKDOWN_LINK_PATTERN)
_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_FENCED_CODE = re.compile(
    r"(?ms)^\s*(?:```|~~~).*?^\s*(?:```|~~~)\s*$"
)
_MATH = re.compile(r"\\\(.+?\\\)|\\\[.+?\\\]|\$\$.+?\$\$", re.DOTALL)
_PLAIN_INLINE_MATH = re.compile(
    r"(?<![A-Za-z0-9_`])"
    r"([A-Z](?:_(?:[A-Za-z0-9]+|\{[^{}\n]+\})))"
    r"(?![A-Za-z0-9_`])"
)
_PLAIN_EQUATION = re.compile(
    r"(?<==)"
    r"(\([A-Za-z0-9_{}+\-*/(). ]+\)"
    r"\s*/\s*[A-Za-z][A-Za-z0-9_]*\([^()\n]+\))"
    r"(?=[，。；：、\n]|$)"
)
_CODE_EXPRESSION = re.compile(
    r"(?<![`\w])"
    r"("
    r"(?=[^，。；：、（）\n]*[-+*/])"
    r"[A-Za-z0-9_.$(][A-Za-z0-9_.$()[\]{},+\-*/=<>% ]{4,}"
    r")"
    r"(?=[，。；：、）】\n]|$)"
)
_CITATION = re.compile(
    r"\b[A-Z][a-z]+"
    r"(?:(?:,\s+|,\s+and\s+|\s+and\s+|,\s*)[A-Z][a-z]+)*"
    r"(?:\s+et\s+al\.)?\s*\(\d{4}[a-z]?\)"
)
_TOKEN = re.compile(
    r"(?<![`\w])"
    r"(?:--[A-Za-z0-9][A-Za-z0-9_-]*(?:=[^\s，。；：、]+)?|"
    r"\$[A-Za-z][A-Za-z0-9_]*|"
    r"[A-Za-z][A-Za-z0-9_.$:@|/()\[\]{}=,+*<>%-]*)"
    r"(?![`\w])"
)
_ENGLISH_PROSE_LINE = re.compile(r"^[^`\u3400-\u9fff]*[A-Za-z]+(?:\s+[A-Za-z]+){4,}[^`]*$")
_QUOTED_TECHNICAL = re.compile(
    r"(?P<open>[“\"])(?P<body>[A-Za-z][A-Za-z0-9_ .:/=+\-]{8,})"
    r"(?P<close>[”\"])"
)
_TECHNICAL_PHRASES = tuple(sorted({
    "Report Workspace", "term structure", "roll yield", "time series",
    "double sort", "long gate", "short gate", "raw factor",
    "conditional factor", "executable strategy", "warm up",
}, key=len, reverse=True))
_NON_CODE_NAMES = {
    "AppKit", "ChatGPT", "FactorTester", "GitHub", "KaTeX", "MathJax",
    "MaxA", "MaxB", "NautilusTrader", "Python", "QuantConnect", "Sparkle",
    "Swift", "SwiftUI", "Yang-Zhang", "Parkinson", "carry", "gap",
}


def format_inline_math(value: str) -> tuple[str, list[str]]:
    """Promote unambiguous subscript variables to inline LaTeX."""
    protected = _protected_ranges(value)
    replacements = [
        (match.start(), match.end(), rf"\({match.group(1)}\)")
        for match in _PLAIN_EQUATION.finditer(value)
        if not _overlaps(match.span(), protected)
    ]
    protected.extend((start, end) for start, end, _ in replacements)
    replacements.extend([
        (match.start(), match.end(), rf"\({match.group(1)}\)")
        for match in _PLAIN_INLINE_MATH.finditer(value)
        if not _overlaps(match.span(), protected)
    ])
    result = value
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]
    return result, [value[start:end] for start, end, _ in replacements]


def format_inline_code(value: str) -> tuple[str, list[str]]:
    """Wrap unambiguous technical English tokens without touching prose names."""
    protected = _protected_ranges(value)
    replacements: list[tuple[int, int, str]] = []
    for match in _QUOTED_TECHNICAL.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        replacements.append((
            match.start(), match.end(),
            f"{match.group('open')}`{match.group('body')}`{match.group('close')}",
        ))
        protected.append(match.span())
    for match in _CODE_EXPRESSION.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        expression = match.group(1)
        leading = expression[:len(expression) - len(expression.lstrip())]
        trailing = expression[len(expression.rstrip()):]
        code = expression.strip()
        replacements.append((
            match.start(), match.end(), f"{leading}`{code}`{trailing}",
        ))
        protected.append(match.span())
    for phrase in _TECHNICAL_PHRASES:
        for match in re.finditer(
            rf"(?<![`\w]){re.escape(phrase)}(?![`\w])",
            value,
            flags=re.IGNORECASE,
        ):
            if _overlaps(match.span(), protected):
                continue
            replacements.append((
                match.start(), match.end(), f"`{match.group(0)}`",
            ))
            protected.append(match.span())
    for match in _TOKEN.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        token = match.group(0)
        if token in _NON_CODE_NAMES or _is_english_prose_line(value, match):
            continue
        replacements.append((match.start(), match.end(), f"`{token}`"))
        protected.append(match.span())
    result = value
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result, [value[start:end] for start, end, _ in sorted(replacements)]


def unformatted_technical_tokens(value: str) -> list[str]:
    """Return tokens that the canonical authoring policy would format."""
    _, tokens = format_inline_code(value)
    return tokens


def _protected_ranges(value: str) -> list[tuple[int, int]]:
    ranges = [
        match.span()
        for pattern in (
            _MARKDOWN_LINK, _INLINE_CODE, _FENCED_CODE, _MATH, _CITATION,
        )
        for match in pattern.finditer(value)
    ]
    offset = 0
    for line in value.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if _ENGLISH_PROSE_LINE.fullmatch(content.strip()):
            ranges.append((offset, offset + len(content)))
        offset += len(line)
    return ranges


def _is_english_prose_line(value: str, match: re.Match[str]) -> bool:
    start = value.rfind("\n", 0, match.start()) + 1
    end = value.find("\n", match.end())
    if end < 0:
        end = len(value)
    line = value[start:end].strip()
    return not _HAN.search(line) and bool(_ENGLISH_PROSE_LINE.fullmatch(line))


def _overlaps(
    span: tuple[int, int], protected: list[tuple[int, int]],
) -> bool:
    return any(span[0] < end and span[1] > start for start, end in protected)
