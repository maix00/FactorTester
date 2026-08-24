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


def test_legacy_source_browser_and_templates_are_removed() -> None:
    app_factory = (ROOT / "server/__init__.py").read_text(encoding="utf-8")

    assert not (ROOT / "server/core.py").exists()
    assert not (ROOT / "server/scan_tools.py").exists()
    assert "core_bp" not in app_factory
    assert "template_folder=None" in app_factory
    assert "static_folder=None" in app_factory
    assert not (ROOT / "tools/data/tech_docs/tool_docs.py").exists()
    assert not (ROOT / "tools/decorators/tech_docs").exists()
    assert not (ROOT / "templates").exists()
    assert not (ROOT / "static/css").exists()
    assert not (ROOT / "static/js").exists()


def test_business_service_does_not_register_browser_pages() -> None:
    app_factory = (ROOT / "server/__init__.py").read_text(encoding="utf-8")
    auth = (ROOT / "server/auth.py").read_text(encoding="utf-8")
    http_auth = (ROOT / "server/services/http_auth.py").read_text(encoding="utf-8")
    custom_factors = (ROOT / "server/modules/custom_factors/catalog_routes.py").read_text(encoding="utf-8")
    admin = (ROOT / "server/admin.py").read_text(encoding="utf-8")
    operations = (ROOT / "server/server_operations.py").read_text(encoding="utf-8")

    assert "render_template" not in app_factory
    assert "methods=['GET', 'POST']" not in auth
    assert "render_template" not in auth
    assert "redirect('/login')" not in http_auth
    assert "render_template" not in custom_factors
    assert "render_template" not in admin
    assert "render_template" not in operations


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
        TechnicalDocsLibrary(tmp_path)


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
        TechnicalDocsLibrary(tmp_path)


def test_content_is_compiled_once_at_startup(tmp_path: Path) -> None:
    source = tmp_path / "page.md"
    source.write_text("## Original {#original}\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"guide","source":"page.md"}]}]}',
        encoding="utf-8",
    )
    library = TechnicalDocsLibrary(tmp_path)

    source.write_text("## Changed {#changed}\n", encoding="utf-8")

    assert library.page("page")["headings"] == [
        {"id": "original", "title": "Original", "level": "h2"}
    ]


def test_cross_page_anchor_and_canonical_paths_are_validated(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "## Page {#page}\n\nPath: `missing.py`. [missing](/docs/other#missing)\n",
        encoding="utf-8",
    )
    (tmp_path / "other.md").write_text("## Other {#other}\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"implementation","source":"page.md",'
        '"canonical_paths":["missing.py"]},'
        '{"slug":"other","title":"Other","summary":"Summary",'
        '"kind":"guide","source":"other.md"}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical code path does not exist"):
        TechnicalDocsLibrary(tmp_path, code_root=tmp_path)

    (tmp_path / "missing.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown technical docs anchor"):
        TechnicalDocsLibrary(tmp_path, code_root=tmp_path)


def test_embedded_images_are_rejected_at_startup(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "## Page {#page}\n\n![remote](https://example.test/image.png)\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        '{"schema_version":1,"title":"Docs","default_page":"page",'
        '"sections":[{"id":"one","title":"One","pages":['
        '{"slug":"page","title":"Page","summary":"Summary",'
        '"kind":"guide","source":"page.md"}]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="embedded images"):
        TechnicalDocsLibrary(tmp_path)
