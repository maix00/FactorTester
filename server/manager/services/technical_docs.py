"""Compiled public technical-document catalog and restricted Markdown renderer."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from markdown_it import MarkdownIt
import nh3

_ANCHOR = re.compile(r"\s+\{#([a-z0-9][a-z0-9-]*)\}\s*$")
_HREF = re.compile(r'href="([^"]+)"')
_INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_KINDS = {"guide", "feature", "implementation", "concept", "troubleshooting", "change"}
_SAFE_EXTERNAL_SCHEMES = {"http", "https"}
_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h2", "h3", "h4",
    "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td",
    "th", "thead", "tr", "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "code": {"class"},
    "h2": {"id"}, "h3": {"id"}, "h4": {"id"},
}


class TechnicalDocsLibrary:
    """Compile an explicit public corpus once; request handlers only read it."""

    def __init__(self, root: Path, *, code_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.code_root = (code_root or self.root.parent).resolve()
        self._index, self._pages = self._compile()

    def index(self) -> dict[str, object]:
        return deepcopy(self._index)

    def page(self, slug: str) -> dict[str, object]:
        try:
            return deepcopy(self._pages[slug])
        except KeyError as exc:
            raise KeyError(slug) from exc

    def _manifest(self) -> dict[str, object]:
        data = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("technical docs manifest schema is invalid")
        sections = data.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError("technical docs sections are required")
        pages = [page for section in sections for page in section.get("pages", [])]
        slugs = [str(page.get("slug", "")) for page in pages]
        if not slugs or len(slugs) != len(set(slugs)) or data.get("default_page") not in slugs:
            raise ValueError("technical docs page slugs are invalid")
        for page in pages:
            if page.get("kind") not in _KINDS:
                raise ValueError("technical docs page kind is invalid")
            if not all(str(page.get(key, "")).strip() for key in ("title", "summary", "source")):
                raise ValueError("technical docs page metadata is incomplete")
            source = (self.root / str(page["source"])).resolve()
            if self.root not in source.parents or source.suffix != ".md" or not source.is_file():
                raise ValueError("technical docs source is invalid")
        return data

    @staticmethod
    def _renderer() -> MarkdownIt:
        return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")

    def _entries(self, manifest: dict[str, object]) -> list[dict[str, object]]:
        return [dict(page, section_id=section["id"], section_title=section["title"])
                for section in manifest["sections"] for page in section["pages"]]

    def _render(self, metadata: dict[str, object]) -> tuple[str, list[dict[str, str]], str]:
        source = (self.root / str(metadata["source"])).read_text(encoding="utf-8")
        renderer = self._renderer()
        tokens = renderer.parse(source)
        headings: list[dict[str, str]] = []
        used: set[str] = set()
        for index, token in enumerate(tokens):
            if token.type == "image" or any(
                child.type == "image" for child in (token.children or [])
            ):
                raise ValueError("technical docs do not permit embedded images")
            if token.type != "heading_open" or index + 1 >= len(tokens):
                continue
            inline = tokens[index + 1]
            match = _ANCHOR.search(inline.content)
            if not match:
                raise ValueError(f"heading requires an explicit stable anchor: {inline.content}")
            anchor = match.group(1)
            if anchor in used:
                raise ValueError(f"duplicate technical docs anchor: {anchor}")
            used.add(anchor)
            inline.content = _ANCHOR.sub("", inline.content)
            if inline.children and inline.children[-1].type == "text":
                inline.children[-1].content = _ANCHOR.sub("", inline.children[-1].content)
            token.attrSet("id", anchor)
            headings.append({"id": anchor, "title": inline.content, "level": token.tag})
        html = renderer.renderer.render(tokens, renderer.options, {})
        sanitized = nh3.clean(
            html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            clean_content_tags={"script", "style", "iframe", "object"},
            url_schemes=_SAFE_EXTERNAL_SCHEMES,
        )
        return sanitized, headings, source

    def _validate_code_paths(self, entry: dict[str, object]) -> None:
        paths = entry.get("canonical_paths", [])
        if entry["kind"] == "implementation" and not paths:
            raise ValueError(f"implementation document has no canonical paths: {entry['slug']}")
        if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
            raise ValueError("technical docs canonical paths are invalid")
        for relative in paths:
            candidate = (self.code_root / relative).resolve()
            if self.code_root != candidate and self.code_root not in candidate.parents:
                raise ValueError(f"canonical code path escapes repository: {relative}")
            if not candidate.exists():
                raise ValueError(f"canonical code path does not exist: {relative}")

    def _validate_document_code_paths(self, entry: dict[str, object], source: str) -> None:
        declared = {str(path).rstrip("/") for path in entry.get("canonical_paths", [])}
        mentioned = {
            value.rstrip("/")
            for value in _INLINE_CODE.findall(source)
            if ("/" in value or value.endswith((".py", ".js", ".swift")))
            and not value.startswith(("http://", "https://"))
        }
        if entry["kind"] == "implementation" and mentioned != declared:
            missing = sorted(mentioned - declared)
            unmentioned = sorted(declared - mentioned)
            raise ValueError(
                f"canonical code path metadata does not match {entry['slug']}: "
                f"undeclared={missing}, unmentioned={unmentioned}"
            )

    @staticmethod
    def _validate_links(slug: str, html: str, anchors: dict[str, set[str]]) -> None:
        for href in _HREF.findall(html):
            parsed = urlparse(href)
            if parsed.scheme:
                if parsed.scheme not in _SAFE_EXTERNAL_SCHEMES:
                    raise ValueError(f"unsafe technical docs link: {href}")
                continue
            if parsed.netloc:
                raise ValueError(f"protocol-relative technical docs link is forbidden: {href}")
            target_slug = slug
            if parsed.path:
                if not parsed.path.startswith("/docs/"):
                    raise ValueError(f"internal technical docs link must use /docs/<slug>: {href}")
                target_slug = unquote(parsed.path.removeprefix("/docs/")).strip("/")
            if target_slug not in anchors:
                raise ValueError(f"unknown technical docs link: {target_slug}")
            if parsed.fragment and unquote(parsed.fragment) not in anchors[target_slug]:
                raise ValueError(f"unknown technical docs anchor: {href}")

    def _compile(self) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        manifest = self._manifest()
        entries = self._entries(manifest)
        positions = {str(entry["slug"]): index for index, entry in enumerate(entries)}
        rendered: dict[str, tuple[str, list[dict[str, str]], str]] = {}
        for entry in entries:
            self._validate_code_paths(entry)
            rendered[str(entry["slug"])] = self._render(entry)
        anchors = {slug: {heading["id"] for heading in value[1]}
                   for slug, value in rendered.items()}
        pages: dict[str, dict[str, object]] = {}
        search, texts = [], []
        for slug, index in positions.items():
            entry = entries[index]
            html, headings, source = rendered[slug]
            self._validate_document_code_paths(entry, source)
            self._validate_links(slug, html, anchors)
            related = []
            for target in entry.get("related", []):
                if target not in positions:
                    raise ValueError(f"unknown related technical document: {target}")
                related.append(entries[positions[target]])
            pages[slug] = {
                "success": True, **entry, "html": html, "headings": headings,
                "related_pages": related,
                "previous": entries[index - 1] if index else None,
                "next": entries[index + 1] if index + 1 < len(entries) else None,
            }
            texts.append(source)
            search.append({
                "slug": slug, "title": entry["title"], "summary": entry["summary"],
                "kind": entry["kind"], "headings": headings,
                "text": re.sub(r"[`#*>{}|]", " ", source),
            })
        revision = sha256("".join(texts).encode()).hexdigest()
        index = {
            "success": True, "title": manifest["title"],
            "default_page": manifest["default_page"],
            "revision": f"sha256:{revision}", "sections": manifest["sections"],
            "search": search,
        }
        return index, pages
