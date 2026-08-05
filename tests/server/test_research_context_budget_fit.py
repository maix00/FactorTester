from server.services.research_graph.branch.context_budget import (
    fit_compacted_context,
    with_context_bytes,
)


def test_final_context_fit_preserves_routing_while_removing_optional_prose():
    context = {
        "branch": {"branch_id": "branch-1"},
        "next_actions": [{
            "action_id": "entry.assess",
            "command": "run assessment",
            "instruction": "先完成节点检查，再复用同一命令推进",
            "requirement_ids": ["requirement-1"],
            "reason": "解释" * 120,
        }],
        "research_cycle": {
            "obligations": [{
                "obligation_id": "obligation-1",
                "materiality": "high",
                "detail_ref": "research-cycle-object:obligation:obligation-1",
                "question_summary": "问题" * 120,
            }],
            "open_obligations": [{
                "obligation_id": "obligation-1",
                "materiality": "high",
                "detail_ref": "research-cycle-object:obligation:obligation-1",
                "question_summary": "问题" * 120,
            }],
        },
        "entry_requirements": [{
            "requirement_id": "requirement-1",
            "detail_ref": "entry-requirement:" + "x" * 120,
        }],
        "packet_compaction": {
            "mode": "lazy_contract_details",
            "detail_command": (
                "factortester research-graph requirement-detail "
                "<instance-id> <branch-id> <requirement-id>"
            ),
        },
    }

    fitted = fit_compacted_context(context, target_bytes=550)

    assert with_context_bytes(fitted) <= 550
    assert fitted["branch"]["branch_id"] == "branch-1"
    assert fitted["next_actions"][0]["action_id"] == "entry.assess"
    assert fitted["next_actions"][0]["command"] == "run assessment"
    assert fitted["next_actions"][0]["instruction"] == (
        "先完成节点检查，再复用同一命令推进"
    )
    assert fitted["research_cycle"]["open_obligations"][0][
        "obligation_id"
    ] == "obligation-1"
    assert fitted["entry_requirements"][0]["requirement_id"] == "requirement-1"
    assert "detail_ref" not in fitted["entry_requirements"][0]
    assert "reason" not in fitted["next_actions"][0]
    for field in ("obligations", "open_obligations"):
        assert "question_summary" not in fitted["research_cycle"][field][0]
        assert "detail_ref" not in fitted["research_cycle"][field][0]
        assert "materiality" not in fitted["research_cycle"][field][0]


def test_final_context_fit_drops_only_closed_obligation_history():
    context = {
        "research_cycle": {
            "obligations": [
                {"obligation_id": "closed", "status": "discharged"},
                {"obligation_id": "active", "status": "bounded"},
            ],
            "open_obligations": [],
        },
        "next_actions": [{
            "action_id": "edge.choose",
            "command": "choose edge",
            "reason": "r" * 100,
            "then": "t" * 100,
        }],
    }

    fitted = fit_compacted_context(context, target_bytes=390)

    assert with_context_bytes(fitted) <= 390
    assert fitted["research_cycle"]["obligations"] == [{
        "obligation_id": "active",
        "status": "bounded",
    }]
    assert fitted["research_cycle"]["closed_obligation_count"] == 1
