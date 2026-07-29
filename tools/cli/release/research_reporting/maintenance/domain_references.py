"""Resolve persisted factor and product names into typed report references."""

from __future__ import annotations

import re
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
_QUALIFIED_PRODUCT = re.compile(
    r"(?<![A-Z0-9.])"
    r"([A-Z]{1,3}\.(?:DCE|CZC|SHF|INE|GFE|CFFEX))"
    r"(?![A-Z0-9.])"
)
_CATALOG_PRODUCT = re.compile(
    r"\b([A-Z]{1,3}\.(?:DCE|CZC|SHF|INE|GFE|CFFEX))\b"
)
_CATALOG_SUFFIXES = {".json", ".md", ".markdown", ".yaml", ".yml"}


@dataclass(frozen=True)
class DomainReferenceCatalog:
    factor_families: frozenset[str]
    qualified_products: frozenset[str]
    product_by_symbol: dict[str, str]


def link_domain_references(
    value: str, *, package_root: Path,
) -> tuple[str, list[str]]:
    """Link only names resolved by the package's real factor/product catalogs."""
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
                family=match.group(1), token=token,
            )
            replacements.append((
                match.start(), match.end(), replacement,
                "factor" if match.group(2) else "factor_family",
            ))
            protected.append(match.span())

    for match in _QUALIFIED_PRODUCT.finditer(value):
        if _overlaps(match.span(), protected):
            continue
        product = match.group(1)
        if product not in catalog.qualified_products:
            continue
        replacements.append((
            match.start(), match.end(),
            _product_link(product, product), "product",
        ))
        protected.append(match.span())

    for symbol, product in sorted(
        catalog.product_by_symbol.items(), key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = re.compile(
            rf"(?<![A-Z0-9.`]){re.escape(symbol)}(?![A-Z0-9.`])"
        )
        for match in pattern.finditer(value):
            if _overlaps(match.span(), protected):
                continue
            replacements.append((
                match.start(), match.end(),
                _product_link(product, symbol), "product",
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
        profile_root / "factor-worktree",
        user_root / "personal-workspace" / "factor-library",
    ]
    families = {
        path.stem
        for root in factor_roots
        for directory in ("custom_factors", "public_factors")
        for path in (root / directory).glob("*.py")
        if path.stem != "__init__"
    }
    products = _package_products(package_root)
    by_symbol: dict[str, str] = {}
    ambiguous: set[str] = set()
    for product in products:
        symbol = product.split(".", 1)[0]
        existing = by_symbol.get(symbol)
        if existing is not None and existing != product:
            ambiguous.add(symbol)
        else:
            by_symbol[symbol] = product
    for symbol in ambiguous:
        by_symbol.pop(symbol, None)
    for family in families:
        by_symbol.pop(family, None)
    return DomainReferenceCatalog(
        factor_families=frozenset(families),
        qualified_products=frozenset(products),
        product_by_symbol=by_symbol,
    )


def _package_products(package_root: Path) -> set[str]:
    products: set[str] = set()
    for path in package_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _CATALOG_SUFFIXES:
            continue
        relative = path.relative_to(package_root)
        if ".git" in relative.parts or "authoring" in relative.parts:
            continue
        try:
            value = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        products.update(_CATALOG_PRODUCT.findall(value))
    return products


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
        return _factor_link(family=family, token=token), (
            "factor" if separator else "factor_family"
        )
    if token in catalog.qualified_products:
        return _product_link(token, token), "product"
    product = catalog.product_by_symbol.get(token)
    if product is not None:
        return _product_link(product, token), "product"
    return None


def _factor_link(*, family: str, token: str) -> str:
    if token == family:
        return typed_markdown_link(
            kind="factor_family",
            target_ref=f"factor-family:{family}",
            label=family,
        )
    suffix = token[len(family):]
    return typed_markdown_link(
        kind="factor", target_ref=f"factor:{token}", label=family,
    ) + f"`{suffix}`"


def _product_link(product: str, label: str) -> str:
    return typed_markdown_link(
        kind="product", target_ref=f"product:{product}", label=label,
    )


def _overlaps(
    span: tuple[int, int], protected: list[tuple[int, int]],
) -> bool:
    return any(span[0] < end and span[1] > start for start, end in protected)
