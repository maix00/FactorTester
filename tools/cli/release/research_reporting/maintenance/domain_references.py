"""Resolve only versioned factor names into typed report references.

Products, contracts, continuous contracts, and Profiles are not inferred from
prose. Their display labels are ambiguous, so authoring commands must resolve a
real domain object before emitting a typed link.
"""

from __future__ import annotations

import re
import subprocess
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..authoring.inline_links import typed_markdown_link


_MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\([^) \n]+(?: [^)]+)?\)")
_INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_FENCED_CODE = re.compile(
    r"(?ms)^\s*(?:```|~~~).*?^\s*(?:```|~~~)\s*$"
)
_MATH = re.compile(r"\\\(.+?\\\)|\\\[.+?\\\]|\$\$.+?\$\$", re.DOTALL)


@dataclass(frozen=True)
class FactorSourceReference:
    family: str
    scope: str
    relative_path: str
    revision: str
    blob_hash: str


@dataclass(frozen=True)
class DomainReferenceCatalog:
    factor_families: dict[str, FactorSourceReference]


def link_domain_references(
    value: str, *, package_root: Path,
) -> tuple[str, list[str]]:
    """Link factor names only when their committed source can be resolved."""
    catalog = load_domain_reference_catalog(str(package_root.resolve()))
    protected = [
        match.span()
        for pattern in (_MARKDOWN_LINK, _FENCED_CODE, _MATH)
        for match in pattern.finditer(value)
    ]
    replacements: list[tuple[int, int, str, str]] = []
    for match in _INLINE_CODE.finditer(value):
        replacement = _domain_link(match.group(1), catalog)
        if replacement is None:
            protected.append(match.span())
            continue
        replacements.append((
            match.start(), match.end(), replacement[0], replacement[1],
        ))
        protected.append(match.span())

    for family in sorted(catalog.factor_families, key=len, reverse=True):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_`])({re.escape(family)})"
            rf"((?:\|[^\s，。；：、]+)*)"
            rf"(?![A-Za-z0-9_`])"
        )
        for match in pattern.finditer(value):
            if _overlaps(match.span(), protected):
                continue
            token = match.group(1) + match.group(2)
            replacement = _factor_link(
                source=catalog.factor_families[family], token=token,
            )
            replacements.append((
                match.start(), match.end(), replacement,
                "factor" if match.group(2) else "factor_family",
            ))
            protected.append(match.span())

    result = value
    for start, end, replacement, _ in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    reasons = [item[3] for item in sorted(replacements)]
    return result, list(dict.fromkeys(reasons))


@lru_cache(maxsize=64)
def load_domain_reference_catalog(
    package_root_value: str,
) -> DomainReferenceCatalog:
    package_root = Path(package_root_value)
    profile_root, user_root = _owner_roots(package_root)
    factor_roots = [
        (
            profile_root / "factor-worktree",
            f"profile-{profile_root.name}",
        ),
        (
            user_root / "personal-workspace" / "factor-library",
            "personal",
        ),
    ]
    families: dict[str, FactorSourceReference] = {}
    blocked: set[str] = set()
    for root, scope in factor_roots:
        for path in _factor_files(root):
            family = path.stem
            if family in families or family in blocked:
                continue
            source = _versioned_factor_source(
                root=root, path=path, scope=scope,
            )
            if source is None:
                blocked.add(family)
            else:
                families[family] = source
    return DomainReferenceCatalog(factor_families=families)


def _owner_roots(package_root: Path) -> tuple[Path, Path]:
    if package_root.parent.name != "research":
        return package_root.parent, package_root.parent
    profile_root = package_root.parent.parent
    user_root = profile_root.parent.parent
    return profile_root, user_root


def _domain_link(
    token: str, catalog: DomainReferenceCatalog,
) -> tuple[str, str] | None:
    family, separator, _ = token.partition("|")
    if family in catalog.factor_families:
        return _factor_link(
            source=catalog.factor_families[family], token=token,
        ), (
            "factor" if separator else "factor_family"
        )
    return None


def _factor_link(*, source: FactorSourceReference, token: str) -> str:
    family = source.family
    if token == family:
        return typed_markdown_link(
            kind="factor_family",
            target_ref=_factor_target(
                prefix="factor-family", source=source, value=family,
            ),
            label=family,
        )
    suffix = token[len(family):]
    return typed_markdown_link(
        kind="factor",
        target_ref=_factor_target(
            prefix="factor", source=source, value=token,
        ),
        label=family,
    ) + f"`{suffix}`"


def _factor_files(root: Path) -> list[Path]:
    return sorted(
        path
        for directory in ("custom_factors", "public_factors")
        for path in (root / directory).glob("*.py")
        if path.stem != "__init__"
    )


def _versioned_factor_source(
    *, root: Path, path: Path, scope: str,
) -> FactorSourceReference | None:
    repository = _git(root, "rev-parse", "--show-toplevel")
    revision = _git(root, "rev-parse", "HEAD")
    if repository is None or revision is None:
        return None
    repository_root = Path(repository)
    try:
        relative_path = path.resolve().relative_to(
            repository_root.resolve()
        ).as_posix()
    except ValueError:
        return None
    tracked = _git(
        repository_root, "ls-files", "--error-unmatch", "--", relative_path,
    )
    if tracked is None:
        return None
    if subprocess.run(
        ["git", "-C", str(repository_root), "diff", "--quiet", "HEAD", "--",
         relative_path],
        check=False, capture_output=True,
    ).returncode != 0:
        return None
    blob_hash = _git(
        repository_root, "rev-parse", f"HEAD:{relative_path}",
    )
    if blob_hash is None:
        return None
    return FactorSourceReference(
        family=path.stem,
        scope=scope,
        relative_path=relative_path,
        revision=revision,
        blob_hash=blob_hash,
    )


def _factor_target(
    *, prefix: str, source: FactorSourceReference, value: str,
) -> str:
    path = _base64(source.relative_path)
    identity = _base64(value)
    return (
        f"{prefix}:v1:{source.scope}:{path}:{identity}:"
        f"{source.revision}:{source.blob_hash}"
    )


def _base64(value: str) -> str:
    return urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _git(root: Path, *arguments: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False, capture_output=True, text=True,
    )
    if result.returncode:
        return None
    value = result.stdout.strip()
    return value or None


def _overlaps(
    span: tuple[int, int], protected: list[tuple[int, int]],
) -> bool:
    return any(span[0] < end and span[1] > start for start, end in protected)
