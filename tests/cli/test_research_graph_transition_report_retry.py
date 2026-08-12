from types import SimpleNamespace

import pytest

from tools.cli.commands import research_graph_transition_report as retry


class _Client:
    def get_profile_research_branch(self, work_package_ref, branch_id):
        assert work_package_ref == "work-package:package-1"
        assert branch_id == "branch-1"
        return {
            "current_node": "capability_resolution",
            "report_checkpoint": {
                "checkpoint_ref": "trace:transition-1",
                "current_node": "capability_resolution",
            },
        }

    def get_research_graph_node_info(self, instance_id, branch_id):
        assert (instance_id, branch_id) == ("instance-1", "branch-1")
        return {
            "node": {"node_id": "capability_resolution"},
            "report_container": {
                "kind": "special",
                "anchor_node": "hypothesis_preregistration",
                "episode_ref": "capability-detour:origin",
            },
            "capability_detour": {
                "schema_version": 1,
                "episode_id": "capability-detour:origin",
                "status": "retained",
                "resume_node": "hypothesis_preregistration",
                "origin_trace_id": "origin",
                "latest_trace_id": "transition-1",
                "report_container": {
                    "kind": "special",
                    "anchor_node": "hypothesis_preregistration",
                    "episode_ref": "capability-detour:origin",
                },
            },
        }


def test_retry_publishes_latest_transition_without_advancing(monkeypatch):
    scope = SimpleNamespace(
        record={"record_id": "package-1"},
        instance_id="instance-1",
        branch_id="branch-1",
        profile_id="maxa",
        agent_id="research-maxa",
    )
    synchronized = {
        "component_id": "capability-detour",
        "status": "synchronized",
    }
    monkeypatch.setattr(
        retry,
        "synchronize_transition_container",
        lambda *_args, **_kwargs: synchronized,
    )
    calls = []
    monkeypatch.setattr(
        retry,
        "publish_transition_report",
        lambda **kwargs: calls.append(kwargs) or {"status": "published"},
    )

    result = retry.retry_latest_transition_report(
        client=_Client(),
        client_root=SimpleNamespace(),
        local_report=scope,
        narrative_file=None,
    )

    assert result["status"] == "published"
    assert calls[0]["branch"]["report_checkpoint"]["checkpoint_ref"] == (
        "trace:transition-1"
    )
    assert calls[0]["chapter_sync"] == synchronized


def test_retry_rejects_a_stale_transition_carrier(monkeypatch):
    client = _Client()
    original = client.get_profile_research_branch

    def stale(work_package_ref, branch_id):
        value = original(work_package_ref, branch_id)
        value["report_checkpoint"]["current_node"] = "capability_gap"
        return value

    client.get_profile_research_branch = stale
    scope = SimpleNamespace(
        record={"record_id": "package-1"},
        instance_id="instance-1",
        branch_id="branch-1",
        profile_id="maxa",
        agent_id="research-maxa",
    )

    with pytest.raises(ValueError, match="does not match current node"):
        retry.retry_latest_transition_report(
            client=client,
            client_root=SimpleNamespace(),
            local_report=scope,
            narrative_file=None,
        )
