from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from tools.cli.commands import research_report_graph_guard as guard


def _scope():
    return SimpleNamespace(branch_ref="graph-branch:instance:branch")


def _snapshot():
    return {
        "components": [
            {
                "component_id": "chapter-hypothesis", "kind": "chapter",
                "parent_id": None,
            },
            {
                "component_id": "existing", "kind": "entry",
                "parent_id": "chapter-hypothesis",
            },
            {
                "component_id": "chapter-data", "kind": "chapter",
                "parent_id": None,
            },
            {
                "component_id": "historical", "kind": "entry",
                "parent_id": "chapter-data",
            },
            {
                "component_id": "system-obligation-change",
                "kind": "special", "parent_id": "chapter-data",
                "title": "义务变化", "body": "证据覆盖已替换",
                "content": {"ledger_sequence": 16},
                "display_kind": "obligation_changes",
            },
        ],
        "bindings": [{
            "binding_id": "chapter-hypothesis-binding",
            "component_id": "chapter-hypothesis",
            "kind": "graph_reference",
            "target_ref": "node:hypothesis_preregistration",
            "data": {"role": "report_chapter"},
        }, {
            "binding_id": "chapter-data-binding",
            "component_id": "chapter-data",
            "kind": "graph_reference", "target_ref": "node:data_contract",
            "data": {"role": "report_chapter"},
        }, {
            "binding_id": "system-obligation-change-binding",
            "component_id": "system-obligation-change",
            "kind": "graph_reference", "target_ref": "trace:event-16",
            "data": {"role": "obligation_requirements_resolution"},
        }],
    }


def _packet():
    return {
        "node": {"node_id": "hypothesis_preregistration"},
        "report_container": {
            "kind": "chapter",
            "anchor_node": "hypothesis_preregistration",
        },
    }


def test_graph_agent_can_only_write_inside_current_system_container(monkeypatch):
    monkeypatch.setattr(guard, "fetch_graph_node_packet", lambda _scope: _packet())
    monkeypatch.setattr(guard, "load_authoring", lambda _scope: _snapshot())
    result = guard.validate_graph_bound_mutations(_scope(), operations=[{
        "op": "add", "component_id": "new-entry", "kind": "entry",
        "parent_id": "chapter-hypothesis",
    }, {
        "op": "replace", "component_id": "new-entry",
    }])
    assert result["container_component_id"] == "chapter-hypothesis"

    with pytest.raises(ValueError, match="system-owned"):
        guard.validate_graph_bound_mutations(_scope(), operations=[{
            "op": "add", "component_id": "chapter-new", "kind": "chapter",
            "parent_id": None,
        }])
    with pytest.raises(ValueError, match="current Graph container"):
        guard.validate_graph_bound_mutations(_scope(), operations=[{
            "op": "add", "component_id": "wrong", "kind": "entry",
            "parent_id": "chapter-data",
        }])
    guard.validate_graph_bound_mutations(_scope(), operations=[{
        "op": "remove", "component_id": "existing",
    }])
    with pytest.raises(ValueError, match="current Graph container"):
        guard.validate_graph_bound_mutations(_scope(), operations=[{
            "op": "remove", "component_id": "historical",
        }])
    explicit = guard.validate_graph_bound_mutations(_scope(), operations=[{
        "op": "add", "component_id": "historical-follow-up",
        "kind": "special", "parent_id": "chapter-data",
        "target_chapter_id": "chapter-data",
        "display_kind": "obligation_requirement",
    }])
    assert explicit["container_component_id"] == "chapter-hypothesis"
    with pytest.raises(ValueError, match="Graph node chapter"):
        guard.validate_graph_bound_mutations(_scope(), operations=[{
            "op": "add", "component_id": "forged-target",
            "kind": "entry", "parent_id": "historical",
            "target_chapter_id": "historical",
        }])
    with pytest.raises(ValueError, match="system-owned"):
        guard.validate_graph_bound_mutations(_scope(), operations=[{
            "op": "replace", "component_id": "chapter-hypothesis",
        }])
    system_kinds = (
        "capability_detour",
        "graph_continuation",
        "obligation_changes",
        "research_gap",
        "test_result",
    )
    for display_kind in system_kinds:
        operation = {
            "op": "add",
            "component_id": f"fake-{display_kind}",
            "kind": "special",
            "display_kind": display_kind,
            "parent_id": "chapter-hypothesis",
        }
        with pytest.raises(ValueError, match="lifecycle special"):
            guard.validate_graph_bound_mutations(
                _scope(), operations=[operation],
            )


def test_unbound_report_does_not_invoke_graph_authority(monkeypatch):
    monkeypatch.setattr(
        guard, "fetch_graph_node_packet",
        lambda _scope: (_ for _ in ()).throw(AssertionError("called")),
    )
    scope = SimpleNamespace(branch_ref="local-report:branch")
    assert guard.validate_graph_bound_mutations(scope, operations=[{
        "op": "add", "component_id": "chapter", "kind": "chapter",
    }]) == {"status": "unbound"}


def test_explicit_old_chapter_enables_only_historical_reference_authority(
    monkeypatch,
):
    monkeypatch.setattr(guard, "load_authoring", lambda _scope: _snapshot())
    monkeypatch.setattr(
        guard, "fetch_graph_node_packet", lambda _scope: _packet(),
    )

    parent, target, historical = guard.resolve_graph_report_parent(
        _scope(), parent_id=None, target_chapter_id="chapter-data",
    )
    assert (parent, target, historical) == (
        "chapter-data", "chapter-data", True,
    )

    parent, target, historical = guard.resolve_graph_report_parent(
        _scope(), parent_id=None, target_chapter_id="chapter-hypothesis",
    )
    assert (parent, target, historical) == (
        "chapter-hypothesis", "chapter-hypothesis", False,
    )


def _historical_review(component_id: str = "historical"):
    identities = sorted(
        item["component_id"] for item in _snapshot()["components"]
    )
    digest = hashlib.sha256(json.dumps(
        identities, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "schema_version": 1,
        "kind": "historical_source_correction",
        "reviewed_component_count": len(identities),
        "reviewed_component_digest": digest,
        "components": [{
            "component_id": component_id,
            "reason": "人工核对历史源文件后纠正公式",
        }],
    }


def test_reviewed_historical_replace_can_cross_current_graph_container(
    monkeypatch,
):
    monkeypatch.setattr(guard, "load_authoring", lambda _scope: _snapshot())
    monkeypatch.setattr(
        guard, "fetch_graph_node_packet",
        lambda _scope: (_ for _ in ()).throw(AssertionError("called")),
    )

    result = guard.validate_graph_bound_mutations(
        _scope(),
        operations=[{"op": "replace", "component_id": "historical"}],
        historical_review=_historical_review(),
    )

    assert result["container_kind"] == "historical_source_correction"


def test_reviewed_system_special_can_only_drop_machine_content(monkeypatch):
    monkeypatch.setattr(guard, "load_authoring", lambda _scope: _snapshot())
    operation = {
        "op": "replace",
        "component_id": "system-obligation-change",
        "title": "义务变化",
        "body": "证据覆盖已替换",
        "content": None,
        "display_kind": "obligation_changes",
    }
    result = guard.validate_graph_bound_mutations(
        _scope(),
        operations=[operation],
        historical_review=_historical_review("system-obligation-change"),
    )
    assert result["container_kind"] == "historical_source_correction"

    with pytest.raises(ValueError, match="historical source correction"):
        guard.validate_graph_bound_mutations(
            _scope(),
            operations=[{**operation, "title": "伪造标题"}],
            historical_review=_historical_review("system-obligation-change"),
        )


@pytest.mark.parametrize("operation,review,error", [
    (
        {"op": "add", "component_id": "historical"},
        _historical_review(),
        "historical source correction",
    ),
    (
        {"op": "replace", "component_id": "chapter-data"},
        _historical_review("chapter-data"),
        "historical source correction",
    ),
    (
        {"op": "replace", "component_id": "historical"},
        {**_historical_review(), "reviewed_component_digest": "0" * 64},
        "does not match report",
    ),
])
def test_historical_review_stays_bounded(
    monkeypatch, operation, review, error,
):
    monkeypatch.setattr(guard, "load_authoring", lambda _scope: _snapshot())

    with pytest.raises(ValueError, match=error):
        guard.validate_graph_bound_mutations(
            _scope(),
            operations=[operation],
            historical_review=review,
        )
