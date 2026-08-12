from __future__ import annotations

import ast
from pathlib import Path
import re

from tools.cli.release.research_reporting.authoring.special_kinds import (
    SPECIAL_SECTION_DISPLAY_KINDS,
)


_ROOT = Path(__file__).resolve().parents[2]


def test_client_and_cli_share_the_same_special_section_catalog() -> None:
    source = (_ROOT / (
        "apple/Sources/Features/Profiles/"
        "ResearchReport/Tree/ResearchReportSectionDisclosure.swift"
    )).read_text(encoding="utf-8")
    client_kinds = set(re.findall(r'displayKind == "([a-z_]+)"', source))
    assert client_kinds == set(SPECIAL_SECTION_DISPLAY_KINDS)


def test_semantic_special_adds_use_the_shared_operation_builder() -> None:
    roots = [
        _ROOT / "tools/cli/release/research_reporting",
        _ROOT / "tools/cli/release/research_obligations",
    ]
    occurrences: list[Path] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                values = {
                    key.value: value.value
                    for key, value in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                }
                if values.get("op") == "add" and values.get("kind") == "special":
                    occurrences.append(path.relative_to(_ROOT))
    assert occurrences == []
    builder_path = _ROOT / (
        "tools/cli/release/research_reporting/authoring/"
        "special_section_operation.py"
    )
    builder_tree = ast.parse(builder_path.read_text(encoding="utf-8"))
    delegated = [
        node for node in ast.walk(builder_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "add_section_operation"
        and any(
            item.arg == "kind"
            and isinstance(item.value, ast.Constant)
            and item.value.value == "special"
            for item in node.keywords
        )
    ]
    assert len(delegated) == 1
