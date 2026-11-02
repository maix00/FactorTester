"""Editing a report must not implicitly share its bytes with a Manager."""
import ast
from pathlib import Path


def test_local_report_commit_has_no_implicit_network_publisher():
    from tools.cli.release.research_reporting.authoring import tree_publication
    tree = ast.parse(Path(tree_publication.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("public_research" in module or "http" in module for module in imports)
    assert not hasattr(tree_publication, "sync_manager")
