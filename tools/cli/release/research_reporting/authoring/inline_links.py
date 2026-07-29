"""Typed rich-text links for report prose and internally generated lists.

The report tree does not own evidence, obligations, Jobs, or other domain
objects.  It only stores portable Markdown links to those objects.  Bindings
remain an internal audit seam and are deliberately not the rendered UI model.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit


INLINE_LINK_KINDS = frozenset({
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
    "run_spec", "trial_plan", "delta",
})
_REFERENCE = re.compile(r"^[^/\\\s][^/\\]{0,2047}$")
_MARKDOWN_LINK = re.compile(r"(?<!\\)\[([^\]\n]{1,256})\]\(([^\s()]+)\)")
_TYPED_URL = re.compile(r"factortester://[^\s)\]]+")


def typed_markdown_link(*, kind: str, target_ref: str, label: str) -> str:
    """Return a canonical, portable Markdown link to one typed domain object."""
    _validate_kind(kind)
    _validate_reference(target_ref)
    _validate_label(label)
    return f"[{label}](factortester://{kind}/{quote(target_ref, safe='')})"


def validate_inline_links(value: str, *, field: str) -> None:
    """Validate typed URLs while leaving ordinary Markdown links untouched."""
    typed_targets: set[str] = set()
    for match in _MARKDOWN_LINK.finditer(value):
        target = match.group(2)
        if target.startswith("factortester://"):
            _validate_typed_url(target, field=field)
            typed_targets.add(target)
    for match in _TYPED_URL.finditer(value):
        target = match.group(0)
        if target not in typed_targets:
            raise ValueError(
                f"{field} typed report references must use Markdown link syntax"
            )


def typed_link_list(links: list[dict[str, str]]) -> str:
    """Format a system-owned association list; callers retain domain ownership."""
    if not links:
        return ""
    return "\n".join(
        "- " + typed_markdown_link(
            kind=item["kind"], target_ref=item["target_ref"], label=item["label"],
        )
        for item in links
    )


def _validate_typed_url(value: str, *, field: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "factortester" or parsed.query or parsed.fragment:
        raise ValueError(f"{field} typed report reference is invalid")
    _validate_kind(parsed.netloc)
    if not parsed.path.startswith("/") or parsed.path.count("/") != 1:
        raise ValueError(f"{field} typed report reference is invalid")
    encoded = parsed.path[1:]
    target_ref = unquote(encoded)
    _validate_reference(target_ref)
    if quote(target_ref, safe="") != encoded:
        raise ValueError(f"{field} typed report reference must be canonical")


def _validate_kind(value: str) -> None:
    if value not in INLINE_LINK_KINDS:
        raise ValueError("typed report reference kind is invalid")


def _validate_reference(value: str) -> None:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError("typed report reference target is invalid")


def _validate_label(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 256:
        raise ValueError("typed report reference label is invalid")
    if any(character in value for character in "[]\n\r"):
        raise ValueError("typed report reference label is invalid")
