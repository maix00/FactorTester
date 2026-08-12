from __future__ import annotations

import json

from click.testing import CliRunner

from tests._report_removal_support import (
    add as _add,
    args as _args,
    component_ids as _ids,
    patch_scope as _patch,
    scope as _scope,
)
from tools.cli.commands.research_report import report


def test_remove_leaf_ordinary_component(tmp_path, monkeypatch):
    client_root, package, chapter = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    binding = {
        "binding_id": "job", "kind": "job", "target_ref": "job:1",
        "label": "回测", "data": {},
    }
    _add(package, "wrong-entry", "entry", chapter, bindings=[binding])

    result = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "wrong-entry", "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["component_id"] == "wrong-entry"
    assert value["removed_component_count"] == 1
    assert "wrong-entry" not in _ids(package)
    _add(package, "wrong-entry", "entry", chapter, bindings=[binding])
    assert "wrong-entry" in _ids(package)


def test_remove_non_empty_component_requires_explicit_subtree_flag(
    tmp_path, monkeypatch,
):
    client_root, package, chapter = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    _add(package, "ordinary-parent", "section", chapter)
    _add(package, "ordinary-child", "entry", "ordinary-parent")

    result = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "ordinary-parent", "--json",
    ])

    assert result.exit_code == 1
    value = json.loads(result.output)
    assert value["status"] == "rejected"
    assert "--include-children" in value["diagnostics"][0]["message"]
    assert {"ordinary-parent", "ordinary-child"}.issubset(_ids(package))

    retry = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "ordinary-parent",
        "--include-children", "--submission-sequence",
        str(value["submission_sequence"]), "--json",
    ])
    assert retry.exit_code == 0, retry.output
    assert json.loads(retry.output)["removed_component_count"] == 2
    assert not {"ordinary-parent", "ordinary-child"}.intersection(_ids(package))


def test_remove_ordinary_subtree_when_explicit(tmp_path, monkeypatch):
    client_root, package, chapter = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    _add(package, "ordinary-parent", "section", chapter)
    _add(package, "ordinary-child", "entry", "ordinary-parent")

    result = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "ordinary-parent",
        "--include-children", "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["removed_component_count"] == 2
    assert not {"ordinary-parent", "ordinary-child"}.intersection(_ids(package))


def test_remove_rejects_special_target(tmp_path, monkeypatch):
    client_root, package, chapter = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    _add(package, "review", "special", chapter, "external_review")

    result = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "review", "--json",
    ])

    assert result.exit_code == 1
    value = json.loads(result.output)
    assert value["status"] == "rejected"
    assert "特殊小节" in value["diagnostics"][0]["message"]
    assert "review" in _ids(package)


def test_remove_rejects_special_descendant_at_any_depth(
    tmp_path, monkeypatch,
):
    client_root, package, chapter = _scope(tmp_path)
    _patch(monkeypatch, client_root)
    _add(package, "level-one", "section", chapter)
    _add(package, "level-two", "subsection", "level-one")
    _add(
        package, "nested-review", "special", "level-two",
        "external_review",
    )

    result = CliRunner().invoke(report, [
        "remove", *_args(), "--component-id", "level-one",
        "--include-children", "--json",
    ])

    assert result.exit_code == 1
    value = json.loads(result.output)
    assert value["status"] == "rejected"
    message = value["diagnostics"][0]["message"]
    assert "nested-review" in message
    assert "特殊小节" in message
    assert {
        "level-one", "level-two", "nested-review",
    }.issubset(_ids(package))
