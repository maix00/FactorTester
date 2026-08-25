"""Typed rich-text links for report prose and internally generated lists.

The report tree does not own evidence, obligations, Jobs, or other domain
objects.  It only stores portable Markdown links to those objects.  Bindings
remain an internal audit seam and are deliberately not the rendered UI model.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

from tools.factors.factor_set_identity import require_factor_set_reference
from tools.factors.formula_identity import (
    require_factor_family_reference,
    require_factor_reference,
)

from ...report_link_kinds import REPORT_LINK_KINDS
from .reference_target_paths import (
    validate_product_object_target,
    validate_product_series_target,
)

INLINE_LINK_KINDS = REPORT_LINK_KINDS
_REFERENCE = re.compile(r"^[^\\\s]{1,2048}$")
_PROFILE_REVISION_REFERENCE = re.compile(
    r"^profile-revision:v1:[a-z0-9][a-z0-9._-]{0,63}:"
    r"sha256:[0-9a-f]{64}$"
)
MARKDOWN_LABEL_PATTERN = r"(?:\\[\[\]\\]|[^\[\]\\\n]){1,512}"
MARKDOWN_LINK_PATTERN = (
    rf"(?<!\\)\[({MARKDOWN_LABEL_PATTERN})\]\(([^\s()]+)\)"
)
_MARKDOWN_LINK = re.compile(MARKDOWN_LINK_PATTERN)
_TYPED_URL = re.compile(r"factortester://[^\s)\]]+")
_DOMAIN_PREFIXES = {
    "evidence": "evidence:",
    "job": "job:",
    "profile": "profile:",
    "entry_requirement": "requirement:",
}


def typed_markdown_link(*, kind: str, target_ref: str, label: str) -> str:
    """Return a canonical, portable Markdown link to one typed domain object."""
    _validate_kind(kind)
    _validate_reference(target_ref)
    _validate_domain_reference(
        kind=kind, target_ref=target_ref, field="typed report reference",
    )
    _validate_label(label)
    escaped = (
        label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    )
    return f"[{escaped}](factortester://{kind}/{quote(target_ref, safe='')})"


def validate_typed_target(*, kind: str, target_ref: str, field: str) -> None:
    """Validate a stored binding target with the same rules as its typed URL."""
    _validate_kind(kind)
    _validate_reference(target_ref)
    _validate_domain_reference(kind=kind, target_ref=target_ref, field=field)


def validate_inline_links(value: str, *, field: str) -> None:
    """Validate typed URLs while leaving ordinary Markdown links untouched."""
    typed_targets: set[str] = set()
    for match in _MARKDOWN_LINK.finditer(value):
        target = match.group(2)
        if target.startswith("factortester://"):
            decode_typed_url(target, field=field)
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


def decode_typed_url(value: str, *, field: str) -> tuple[str, str]:
    """Validate and decode one canonical typed URL without resolving its object."""
    parsed = urlsplit(value)
    if parsed.scheme != "factortester" or parsed.query or parsed.fragment:
        raise ValueError(f"{field} typed report reference is invalid")
    _validate_kind(parsed.netloc)
    if not parsed.path.startswith("/") or parsed.path.count("/") != 1:
        raise ValueError(f"{field} typed report reference is invalid")
    encoded = parsed.path[1:]
    target_ref = unquote(encoded)
    _validate_reference(target_ref)
    _validate_domain_reference(
        kind=parsed.netloc, target_ref=target_ref, field=field,
    )
    if quote(target_ref, safe="") != encoded:
        raise ValueError(f"{field} typed report reference must be canonical")
    return parsed.netloc, target_ref


def _validate_kind(value: str) -> None:
    if value not in INLINE_LINK_KINDS:
        raise ValueError("typed report reference kind is invalid")


def _validate_reference(value: str) -> None:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError("typed report reference target is invalid")


def _validate_domain_reference(
    *, kind: str, target_ref: str, field: str,
) -> None:
    if kind == "factor":
        validators = (
            require_factor_reference,
            require_factor_family_reference,
            require_factor_set_reference,
        )
        if not any(_accepts(validator, target_ref) for validator in validators):
            raise ValueError(
                f"{field} factor reference must identify one frozen formula"
            )
    elif kind in {"product", "contract"}:
        try:
            validate_product_object_target(target_ref)
        except ValueError as error:
            raise ValueError(
                f"{field} {kind} reference is invalid"
            ) from error
    elif kind == "continuous_contract":
        try:
            validate_product_series_target(target_ref)
        except ValueError as error:
            raise ValueError(
                f"{field} continuous_contract reference is invalid"
            ) from error
    elif kind == "profile_revision":
        if _PROFILE_REVISION_REFERENCE.fullmatch(target_ref) is None:
            raise ValueError(f"{field} profile_revision reference is invalid")
    elif kind in _DOMAIN_PREFIXES:
        prefix = _DOMAIN_PREFIXES[kind]
        if not target_ref.startswith(prefix) or target_ref == prefix:
            raise ValueError(f"{field} {kind} reference is invalid")


def _validate_label(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 256:
        raise ValueError("typed report reference label is invalid")


def _accepts(validator, value: str) -> bool:
    try:
        validator(value)
    except ValueError:
        return False
    return True
    if any(character in value for character in "\n\r"):
        raise ValueError("typed report reference label is invalid")


def unescape_markdown_label(value: str) -> str:
    """Decode only the escapes emitted by ``typed_markdown_link``."""
    return re.sub(r"\\([\\\[\]])", r"\1", value)
