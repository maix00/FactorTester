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


def test_open_lookahead_obligation_blocks_by_machine_requirement() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="lookahead_control",
            status="open",
            requirement_refs=["data-provenance.point-in-time"],
        ),
        provenance_integrity_status="bounded_unverified",
    ) is False


def test_bounded_point_in_time_obligation_permits_bounded_provenance() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="membership_vintage",
            status="bounded",
            requirement_refs=["data-provenance.point-in-time"],
        ),
        provenance_integrity_status="bounded_unverified",
    ) is True


def test_free_text_kind_cannot_substitute_for_machine_requirement() -> None:
    assert data_obligation_gate_satisfied(
        _checkpoint(
            kind="data_provenance",
            status="bounded",
            requirement_refs=[],
        ),
        provenance_integrity_status="bounded_unverified",
    ) is False
