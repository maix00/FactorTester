from __future__ import annotations

from tools.tool_docs import VISIBILITY_ALL, VISIBILITY_PUBLIC, extract_tool_symbols


def test_extract_tool_symbols_public_respects_tech_docs_and_factor_workspace():
    source = """
from tools.decorator.tech_docs import tech_docs
from tools.decorator.factor_workspace import factor_workspace

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
