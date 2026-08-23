"""Public technical-document catalog and restricted Markdown renderer."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from markdown_it import MarkdownIt


_ANCHOR = re.compile(r"\s+\{#([a-z0-9][a-z0-9-]*)\}\s*$")
_DOC_LINK = re.compile(r'href="/docs(?:/([^"#?]+))?(?:#([^"?]+))?"')
_KINDS = {"guide", "feature", "implementation", "concept", "troubleshooting", "change"}


class TechnicalDocsLibrary:
    """Load only explicitly manifested public docs; never traverse source code."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _manifest(self) -> dict[str, object]:
        data = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("technical docs manifest schema is invalid")
        pages = [page for section in data.get("sections", []) for page in section.get("pages", [])]
        slugs = [str(page.get("slug", "")) for page in pages]
        if not slugs or len(slugs) != len(set(slugs)) or data.get("default_page") not in slugs:
            raise ValueError("technical docs page slugs are invalid")
        for page in pages:
            if page.get("kind") not in _KINDS:
                raise ValueError("technical docs page kind is invalid")
            source = (self.root / str(page.get("source", ""))).resolve()
            if self.root not in source.parents or source.suffix != ".md" or not source.is_file():
                raise ValueError("technical docs source is invalid")
        return data

    def _entries(self, manifest: dict[str, object]) -> list[dict[str, object]]:
        return [dict(page, section_id=section["id"], section_title=section["title"])
                for section in manifest["sections"] for page in section["pages"]]

    def _render(self, metadata: dict[str, object]) -> tuple[str, list[dict[str, str]], str]:
        source = (self.root / str(metadata["source"])).read_text(encoding="utf-8")
        renderer = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
        tokens = renderer.parse(source)
        headings: list[dict[str, str]] = []
        used: set[str] = set()
        for index, token in enumerate(tokens):
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
        return renderer.renderer.render(tokens, renderer.options, {}), headings, source

    def index(self) -> dict[str, object]:
        manifest = self._manifest()
        pages = []
        texts = []
        for entry in self._entries(manifest):
            _, headings, source = self._render(entry)
            texts.append(source)
            pages.append({"slug": entry["slug"], "title": entry["title"],
                          "summary": entry["summary"], "kind": entry["kind"],
                          "headings": headings,
                          "text": re.sub(r"[`#*>{}|]", " ", source)})
        revision = sha256("".join(texts).encode()).hexdigest()
        return {"success": True, "title": manifest["title"],
                "default_page": manifest["default_page"],
                "revision": f"sha256:{revision}", "sections": manifest["sections"],
                "search": pages}

    def page(self, slug: str) -> dict[str, object]:
        manifest = self._manifest()
        entries = self._entries(manifest)
        positions = {str(entry["slug"]): index for index, entry in enumerate(entries)}
        if slug not in positions:
            raise KeyError(slug)
        index = positions[slug]
        html, headings, _ = self._render(entries[index])
        for target, _ in _DOC_LINK.findall(html):
            if target and target not in positions:
                raise ValueError(f"unknown technical docs link: {target}")
        related = []
        for target in entries[index].get("related", []):
            if target not in positions:
                raise ValueError(f"unknown related technical document: {target}")
            related.append(entries[positions[target]])
        return {"success": True, **entries[index], "html": html, "headings": headings,
                "related_pages": related,
                "previous": entries[index - 1] if index else None,
                "next": entries[index + 1] if index + 1 < len(entries) else None}
