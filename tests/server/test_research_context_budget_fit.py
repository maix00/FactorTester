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
            "reason": "解释" * 120,
        }],
        "research_cycle": {
            "open_obligations": [{
                "obligation_id": "obligation-1",
                "detail_ref": "research-cycle-object:obligation:obligation-1",
                "question_summary": "问题" * 120,
            }],
        },
        "packet_compaction": {
            "mode": "lazy_contract_details",
            "detail_command": (
                "factortester research step inspect "
                "<instance-id> <branch-id> --output <file>"
            ),
        },
    }

    fitted = fit_compacted_context(context, target_bytes=420)

    assert with_context_bytes(fitted) <= 420
    assert fitted["branch"]["branch_id"] == "branch-1"
    assert fitted["next_actions"][0]["action_id"] == "entry.assess"
    assert fitted["next_actions"][0]["command"] == "run assessment"
    assert fitted["research_cycle"]["open_obligations"][0][
        "obligation_id"
    ] == "obligation-1"
    assert fitted["research_cycle"]["open_obligations"][0]["detail_ref"]
    assert "reason" not in fitted["next_actions"][0]
    assert "question_summary" not in (
        fitted["research_cycle"]["open_obligations"][0]
    )
