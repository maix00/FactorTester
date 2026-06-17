from __future__ import annotations

import os
import time

from tools import tool_docs
from tools.tool_docs import VISIBILITY_ALL, VISIBILITY_PUBLIC, extract_tool_symbols, scan_tool_files


def test_extract_tool_symbols_public_respects_tech_docs_and_factor_workspace():
    source = """
from tools.decorators import tech_docs
from tools.decorators import factor_workspace

@tech_docs
def public_func():
    pass

def private_func():
    pass

@factor_workspace
class PublicClass:
    def visible(self):
        pass
    def _hidden(self):
        pass

class HiddenClass:
    def visible(self):
        pass
"""
    assert extract_tool_symbols(source, visibility=VISIBILITY_PUBLIC) == [
        {"kind": "function", "name": "public_func"},
        {"kind": "class", "name": "PublicClass"},
        {"kind": "method", "name": "PublicClass.visible"},
    ]


def test_extract_tool_symbols_all_keeps_existing_behavior():
    source = """
def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    def visible(self):
        pass
    def _hidden(self):
        pass
"""
    assert extract_tool_symbols(source, visibility=VISIBILITY_ALL) == [
        {"kind": "function", "name": "public_func"},
        {"kind": "class", "name": "PublicClass"},
        {"kind": "method", "name": "PublicClass.visible"},
    ]


def test_scan_tool_files_uses_cache_until_mtime_changes(monkeypatch, tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    sample = tools_dir / "sample.py"
    sample.write_text(
        "# =============================================================================\n"
        "# sample\n"
        "# =============================================================================\n"
        "def visible():\n"
        "    pass\n",
        encoding="utf-8",
    )

    calls = {"count": 0}
    original = tool_docs.parse_tool_file

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tool_docs, "parse_tool_file", wrapped)

    first = scan_tool_files(str(tools_dir), include_symbols=True, visibility=VISIBILITY_ALL)
    second = scan_tool_files(str(tools_dir), include_symbols=True, visibility=VISIBILITY_ALL)

    assert len(first) == 1
    assert len(second) == 1
    assert calls["count"] == 1

    time.sleep(0.001)
    os.utime(sample, None)
    third = scan_tool_files(str(tools_dir), include_symbols=True, visibility=VISIBILITY_ALL)

    assert len(third) == 1
    assert calls["count"] == 2
