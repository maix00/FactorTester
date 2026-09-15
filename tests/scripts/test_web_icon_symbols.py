"""Every icon symbol the Web uses must be registered in core/icons.js.

The registry falls back to the generic link glyph for an unknown symbol, so an
unregistered name silently renders the wrong control (the report download
button looked like a chain link).  This guard fails instead of shipping one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "server" / "manager" / "web"

USAGE_PATTERNS = (
    re.compile(r'FTIcons(?:\.node)?\(\s*[\'"]([A-Za-z0-9._-]+)[\'"]'),
    re.compile(r'iconButton\(\s*[^,]+,\s*[\'"]([A-Za-z0-9._-]+)[\'"]'),
    re.compile(r'iconAction\(\s*[^,]+,\s*[^,]+,\s*[\'"]([A-Za-z0-9._-]+)[\'"]'),
    re.compile(r'pageHeader\([^)]*[\'"]([a-z][A-Za-z0-9._-]*)[\'"]\s*\)'),
)


def _registered_symbols() -> set[str]:
    source = (WEB / "core/icons.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"([A-Za-z0-9._-]+)":\s*[\'"]', source, re.M))


def _used_symbols() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for path in WEB.rglob("*.js"):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in USAGE_PATTERNS:
            for name in pattern.findall(text):
                used.setdefault(name, set()).add(str(path.relative_to(WEB)))
    return used


def test_web_icon_symbols_are_registered():
    registered = _registered_symbols()
    assert "arrow.down.circle" in registered
    assert "link" in registered
    missing = {
        name: sorted(files)
        for name, files in _used_symbols().items()
        if name not in registered
    }
    assert not missing, f"unregistered icon symbols render the link glyph: {missing}"


def test_the_download_control_uses_the_registered_download_symbol():
    action = (WEB / "report" / "export-action.js").read_text(encoding="utf-8")
    assert '"arrow.down.circle"' in action
    assert "square.and.arrow.up" not in action
