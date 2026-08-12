from __future__ import annotations

from scripts.worktree_manager_sqlite_ui import decorate_sqlite_html


def test_sqlite_html_gets_collapsible_full_name_navigation() -> None:
    source = (
        b"<html><head></head><body>"
        b'<div id="sidebar"><ul class="nav flex-column nav-pills">'
        b'<li class="table-link"><a title="a_very_long_table_name">a_very_...</a></li>'
        b"</ul></div></body></html>"
    )

    result = decorate_sqlite_html(source, "text/html; charset=utf-8").decode()

    assert "ft-sqlite-table-list" in result
    assert "overflow: auto" in result
    assert "ft-sqlite-sidebar-resizer" in result
    assert "调整数据表栏宽度" in result
    assert "fullName" in result
    assert 'title="a_very_long_table_name"' in result


def test_sqlite_html_decoration_is_idempotent() -> None:
    source = b"<html><head></head><body></body></html>"
    once = decorate_sqlite_html(source, "text/html")
    twice = decorate_sqlite_html(once, "text/html")
    assert twice == once


def test_sqlite_html_leaves_non_html_responses_unchanged() -> None:
    source = b'{"rows": []}'
    assert decorate_sqlite_html(source, "application/json") == source
