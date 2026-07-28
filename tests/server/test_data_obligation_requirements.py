from server.services.research_graph.research_cycle.requirements import (
    data_obligation_gate_satisfied,
)


def _checkpoint(*, kind: str, status: str, requirement_refs: list[str]) -> dict:
    return {
        "obligations": [{
            "obligation_kind": kind,
            "requirement_refs": requirement_refs,
            "materiality": "decision_blocking",
            "status": status,
        }],
    }


def test_open_data_scope_obligation_blocks_by_machine_requirement() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="data_availability_for_trial_design",
            status="open",
            requirement_refs=["data-availability.scope"],
        ),
    ) is False


def test_bounded_data_scope_obligation_permits_transition() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="data_availability_for_trial_design",
            status="bounded",
            requirement_refs=["data-availability.scope"],
        ),
    ) is True


def test_unrelated_free_text_obligation_does_not_create_data_gate() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="data_provenance",
            status="bounded",
            requirement_refs=[],
        ),
    ) is True
