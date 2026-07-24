from pathlib import Path

from flask import Flask, render_template, render_template_string


ROOT = Path(__file__).resolve().parents[2]


def _app() -> Flask:
    return Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )


def _render(template: str, *, embedded: bool) -> str:
    app = _app()
    query = "?presentation=embedded" if embedded else ""
    with app.test_request_context(f"/test{query}"):
        return render_template(template)


def test_shared_home_link_is_only_hidden_in_embedded_presentation() -> None:
    assert "返回首页" in _render(
        "modules/shared/home_back_link.html", embedded=False
    )
    assert "返回首页" not in _render(
        "modules/shared/home_back_link.html", embedded=True
    )


def test_single_factor_account_chrome_is_only_hidden_when_embedded() -> None:
    standalone = _render("single_factor_test.html", embedded=False)
    embedded = _render("single_factor_test.html", embedded=True)

    assert 'id="user-badge"' in standalone
    assert 'id="user-logout-btn"' in standalone
    assert 'id="user-badge"' not in embedded
    assert 'id="user-logout-btn"' not in embedded
    assert "单因子(家族)测试" in embedded
    assert "single_factor_shell.js" in embedded


def test_home_and_technical_docs_drop_standalone_account_chrome_when_embedded(
) -> None:
    for template in ("home.html", "docs.html"):
        standalone = _render(template, embedded=False)
        embedded = _render(template, embedded=True)

        assert 'id="user-area"' in standalone
        assert 'id="user-area"' not in embedded

    assert 'id="shutdown-btn"' in _render("home.html", embedded=False)
    embedded_home = _render("home.html", embedded=True)
    assert 'id="shutdown-btn"' not in embedded_home
    assert "function renderShutdownControl()" in embedded_home
    assert "document.getElementById('shutdown-btn').style" not in embedded_home


def test_docs_keep_internal_breadcrumb_but_drop_home_link_when_embedded() -> None:
    app = _app()
    source = """
    {% from 'docs/_layout.html' import doc_header with context %}
    {{ doc_header('用户手册', '/docs', '标题', '副标题') }}
    """
    with app.test_request_context("/docs/example"):
        standalone = render_template_string(source)
    with app.test_request_context("/docs/example?presentation=embedded"):
        embedded = render_template_string(source)

    assert "返回首页" in standalone
    assert "返回首页" not in embedded
    assert "用户手册" in embedded
    assert 'href="/docs"' in embedded


def test_standalone_only_links_on_special_pages_are_hidden_when_embedded() -> None:
    for template in (
        "admin_users.html",
        "custom_factor_editor.html",
        "docs/user_manual_home.html",
        "factor_library_client.html",
        "local_data.html",
        "price_viewer.html",
        "products.html",
        "server_operations.html",
    ):
        assert "返回首页" in _render(template, embedded=False)
        assert "返回首页" not in _render(template, embedded=True)


def test_server_operations_keep_polling_after_async_process_action() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "templates/server_operations.html"
    ).read_text(encoding="utf-8")

    assert "操作处理中" in source
    assert "[500, 1500, 3500, 7000, 11000]" in source
