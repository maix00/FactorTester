from __future__ import annotations

import pytest

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


def test_research_resume_uses_runtime_profile_without_dropping_local_state(
    monkeypatch,
) -> None:
    requirements = [
        {
            "requirement_id": f"trial_design_validity.requirement_{index}",
            "title_zh": (
                f"第 {index} 项 Trial 设计要求是否已被当前义务和证据覆盖"
            ),
            "mapped_obligation_refs": [f"obligation-{index % 8}"],
        }
        for index in range(12)
    ]
    obligations = [
        {
            "obligation_id": f"obligation-{index}",
            "materiality": "decision_blocking",
            "status": "open",
            "question_summary": (
                f"第 {index} 项当前研究义务需要怎样的 Trial 才能改变证据状态，"
                "并且还存在哪些不能由当前试验回答的边界？"
            ),
            "detail_ref": f"research-cycle-object:obligation:obligation-{index}",
        }
        for index in range(8)
    ]
    source = {
        "graph": "factor-research@v9",
        "branch": {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
            "status": "running",
            "product_group": "china_futures",
            "workspace_id": "workspace-1",
            "capability_resolution_hash": "a" * 64,
            "trial_plan_hash": None,
        },
        "node": {
            "node_id": "validation_design",
            "kind": "validation",
            "purpose": (
                "Freeze selection, holdout, slice, and multiple-testing design."
            ),
        },
        "context_ref": "sha256:" + "b" * 64,
        "budget_profile": {
            "profile_ref": "agent-packet-runtime:" + "c" * 64,
            "profile_hash": "d" * 64,
            "ceiling_bytes": 12288,
        },
        "capabilities": [{
            "capability_id": "research-trial.synthesize",
            "capability_description": (
                "Freeze a TrialPlan whose outcomes, samples, alternatives, "
                "multiplicity and stopping rules can resolve one obligation."
            ),
            "descriptor_hash": "e" * 64,
            "status": "bound",
        }],
        "unresolved_capability_conditions": [],
        "current_obligations": obligations,
        "candidate_trial_frontier": {
            "current_trial_plan_hash": None,
            "trial_stage": None,
            "candidate_plan_refs": [],
            "unassessed_obligation_count": 8,
        },
        "candidate_edges": [{
            "edge_id": "validation_design__trial_execution",
            "to_node": "trial_execution",
            "readiness": "ready",
            "blockers": [],
        }],
        "recommended_edge_ids": ["validation_design__trial_execution"],
        "requires_agent_judgment": True,
        "running_backend_jobs_action": "continue",
        "entry_requirements": requirements,
        "entry_resolution": {
            "reason": "node_entry",
            "status": "pending",
            "resume_node": "validation_design",
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
        "next_bytes": 11588,
    }
    monkeypatch.setattr(
        resume_module,
        "build_graph_branch_next",
        lambda **_kwargs: source,
    )

    packet = resume_module.build_agent_resume_packet(
        owner="alice",
        agent_id="research-maxa",
        role="research",
        instance_id="instance-1",
        branch_id="branch-1",
    )

    assert 6000 < packet["packet_bytes"] <= 12288
    assert packet["research"]["budget_profile"] == source["budget_profile"]
    assert len(packet["research"]["entry_requirements"]) == 12
    assert len(packet["research"]["current_obligations"]) == 8


def test_research_resume_without_runtime_profile_keeps_legacy_ceiling(
    monkeypatch,
) -> None:
    source = {
        "graph": "factor-research@v1",
        "branch": {"instance_id": "instance-1", "branch_id": "branch-1"},
        "node": {"node_id": "validation_design"},
        "context_ref": "sha256:" + "a" * 64,
        "capabilities": [],
        "unresolved_capability_conditions": [],
        "current_obligations": [{
            "obligation_id": f"obligation-{index}",
            "materiality": "decision_blocking",
            "status": "open",
            "question_summary": "x" * 600,
            "detail_ref": f"research-cycle-object:obligation:{index}",
        } for index in range(10)],
        "candidate_trial_frontier": {
            "current_trial_plan_hash": None,
            "trial_stage": None,
            "candidate_plan_refs": [],
            "unassessed_obligation_count": 10,
        },
        "candidate_edges": [],
        "recommended_edge_ids": [],
        "requires_agent_judgment": True,
        "running_backend_jobs_action": "continue",
        "next_bytes": 5900,
    }
    monkeypatch.setattr(
        resume_module,
        "build_graph_branch_next",
        lambda **_kwargs: source,
    )

    with pytest.raises(
        ValueError,
        match="Agent resume packet exceeds 6000 bytes",
    ):
        resume_module.build_agent_resume_packet(
            owner="alice",
            agent_id="research-maxa",
            role="research",
            instance_id="instance-1",
            branch_id="branch-1",
        )
