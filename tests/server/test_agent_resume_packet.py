from __future__ import annotations

from server.services.agent_flow import resume as resume_module


def test_research_resume_compacts_eleven_entry_requirements(
    monkeypatch,
) -> None:
    requirements = [
        {
            "requirement_id": f"factor_semantics.requirement_{index}",
            "title_zh": f"第 {index} 项因子语义要求",
            "gate_policy": "plan_before_exit",
            "mapped_obligation_refs": [],
            "mapped_statuses": [],
            "detail_ref": (
                "graph-requirement:"
                f"factor_semantics.requirement_{index}"
            ),
        }
        for index in range(11)
    ]
    oversized_next = {
        "graph": "factor-research@v9",
        "branch": {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
            "status": "active",
        },
        "node": {
            "node_id": "factor_semantics",
            "kind": "research",
            "purpose": "审查因子语义。",
        },
        "context_ref": "sha256:" + "a" * 64,
        "capabilities": [],
        "unresolved_capability_conditions": [],
        "current_obligations": [],
        "candidate_trial_frontier": {
            "current_trial_plan_hash": None,
            "trial_stage": None,
            "candidate_plan_refs": [],
            "unassessed_obligation_count": 0,
        },
        "changed_refs": [f"evidence:{index}" for index in range(20)],
        "candidate_edges": [{
            "edge_id": "factor_semantics__validation_design",
            "to_node": "validation_design",
            "edge_type": "conditional",
            "risk_level": "L1",
            "readiness": "ready",
            "required_guard_fields": [],
            "required_research_evidence": [],
            "required_transition_facts": [],
            "blockers": [],
            "review_requirement": "none",
            "report_requirement_refs": [
                "report.edge.factor_semantics__validation_design"
            ],
        }],
        "recommended_edge_ids": [
            "factor_semantics__validation_design"
        ],
        "requires_agent_judgment": True,
        "running_backend_jobs_action": "continue",
        "entry_requirements": requirements,
        "entry_resolution": {
            "status": "pending",
            "unresolved_requirement_ids": [
                item["requirement_id"] for item in requirements
            ],
        },
        "entry_requirement_policy": {
            "detail_command": (
                "factortester research-graph requirement-detail "
                "<instance> <branch> <requirement-id>"
            ),
        },
        "node_report_requirement_refs": [
            f"report.requirement.{item['requirement_id']}"
            for item in requirements
        ],
        "next_bytes": 9142,
    }
    monkeypatch.setattr(
        resume_module,
        "build_graph_branch_next",
        lambda **_kwargs: oversized_next,
    )

    packet = resume_module.build_agent_resume_packet(
        owner="alice",
        agent_id="research-maxa",
        role="research",
        budget_period=None,
        instance_id="instance-1",
        branch_id="branch-1",
    )

    assert packet["packet_bytes"] <= 6000
    assert len(packet["research"]["entry_requirements"]) == 11
    assert packet["research"]["entry_requirements"][0] == {
        "requirement_id": "factor_semantics.requirement_0",
        "title_zh": "第 0 项因子语义要求",
        "status": "unresolved",
        "required_action": "load_detail_and_assess",
    }
    assert packet["research"]["candidate_edges"] == [{
        "edge_id": "factor_semantics__validation_design",
        "to_node": "validation_design",
        "readiness": "ready",
        "blockers": [],
    }]
    assert packet["research"]["capabilities"] == []
    assert "changed_refs" not in packet["research"]
    assert "node_report_requirement_refs" not in packet["research"]
    assert oversized_next["graph"] == "factor-research@v9"
    assert oversized_next["next_bytes"] == 9142
