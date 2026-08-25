"""Small source-inspection helpers with no metadata rewriting."""

from __future__ import annotations

import ast


def factor_class_name(source_code: str) -> str:
    """Return the first declared class name from an editable source file."""
    try:
        module = ast.parse(source_code or "")
    except SyntaxError:
        return ""
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            return node.name
    return ""


__all__ = ["factor_class_name"]
