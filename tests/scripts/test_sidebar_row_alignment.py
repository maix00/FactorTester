"""A closable feature entry lines its × up with the opened-tab rows.

An opened tab insets its content with the row's own 8px padding, so a closable
feature entry (server management, technical documentation, settings) must carry
the same inset or its close control sits 8px further right.
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "server" / "manager" / "web"


def test_closable_entry_row_matches_the_opened_tab_inset():
    css = (WEB / "styles" / "app.css").read_text(encoding="utf-8")
    assert ".opened-tab { width: 100%; min-width: 0; border: 0; background: transparent; color: inherit; border-radius: 7px; padding: 6px 8px;" in css
    assert (
        ".nav-singleton { display: flex; align-items: center; min-width: 0;"
        in css
    )
    assert "padding-right: 8px; }" in css


def test_both_sidebar_rows_use_one_close_button_contract():
    css = (WEB / "styles" / "app.css").read_text(encoding="utf-8")
    # The icon-action size is shared by every sidebar row that carries a close.
    assert (
        ":is(.opened-tab, .nav-folder-row, .nav-singleton) > .tab-close"
        in css
    )
