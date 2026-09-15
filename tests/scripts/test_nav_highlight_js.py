"""The feature-entry highlight belongs to the tab's own route.

A tab used to store whatever entry happened to be highlighted when its view
was saved, so switching back to 测试台 replayed 研究台.  The entry a page chose
is now recorded per tab, and the DOM is only a fallback.
"""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "server" / "manager" / "web"


def _node(script: str) -> None:
    result = subprocess.run(
        ["node", script], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_tab_nav_highlight_js():
    _node("tests/js/test_tab_nav_highlight.js")


def test_route_dispatch_nav_js():
    _node("tests/js/test_route_dispatch_nav.js")


def test_active_nav_is_recorded_per_tab():
    coordinator = (WEB / "app" / "coordinator.js").read_text(encoding="utf-8")
    cache = (WEB / "app" / "tab-view-cache.js").read_text(encoding="utf-8")
    # The page's choice is recorded for the active tab...
    assert "session.navRoute = value" in coordinator
    # ...and the tab view stores that recorded choice, not a later DOM sample.
    assert "tabSession(tabID).navRoute" in cache
    assert 'document.querySelector?.(".nav-button.active")' in cache
