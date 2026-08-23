from pathlib import Path

import pytest

from server.manager.services.technical_docs import TechnicalDocsLibrary


ROOT = Path(__file__).resolve().parents[2]


def test_public_catalog_contains_guides_and_implementation_maps() -> None:
    library = TechnicalDocsLibrary(ROOT / "product_docs")
    index = library.index()
    kinds = {page["kind"] for page in index["search"]}

    assert index["default_page"] == "getting-started"
    assert {"guide", "implementation", "concept", "troubleshooting"} <= kinds
    assert library.page("system-overview")["section_title"] == "实现架构"


def test_markdown_disables_embedded_html_and_keeps_stable_anchors(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "## 安全标题 {#safe-heading}\n\n<script>alert(1)</script>\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"guide","source":"page.md"}]}]}',
        encoding="utf-8",
    )

    page = TechnicalDocsLibrary(tmp_path).page("page")

    assert 'id="safe-heading"' in page["html"]
    assert "<script>" not in page["html"]
    assert "&lt;script&gt;" in page["html"]


def test_manifest_cannot_escape_public_content_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "private.md"
    outside.write_text("## Private {#private}", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"guide","source":"../private.md"}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source is invalid"):
        TechnicalDocsLibrary(tmp_path).index()


def test_every_heading_requires_an_explicit_anchor(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text("## Unstable\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"guide","source":"page.md"}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit stable anchor"):
        TechnicalDocsLibrary(tmp_path).page("page")
