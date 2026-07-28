"""Breaking-schema checks for bounded availability profiles."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.services.research_graph.research_cycle.data_availability_evidence import (
    project_availability_evidence,
    validate_availability_request,
)
from tools.data.availability.model import profile_document


def _request() -> dict:
    return validate_availability_request({
        "products": ["A.DCE"],
        "sources": ["Local"],
        "frequencies": ["MIN1"],
    })


def _profile(entry: dict) -> dict:
    return profile_document(
        product_scope=["A.DCE"],
        source_scope=["Local"],
        frequency_scope=["MIN1"],
        probe=False,
        expanded=False,
        entries=[entry],
        as_of=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            {
                "product": "A.DCE",
                "source": "LocalCNFuturesMIN1",
                "status": "available",
                "frequency": "MIN1",
                "point_in_time": False,
            },
            "obsolete point_in_time",
        ),
        (
            {
                "product": "A.DCE",
                "source": "LocalCNFuturesDAY1",
                "status": "available",
                "frequency": "DAY1",
            },
            "frequencies outside request",
        ),
    ],
)
def test_graph_profile_rejects_obsolete_or_out_of_scope_entries(
    entry: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        project_availability_evidence(
            profile=_profile(entry),
            request=_request(),
            checkpoint={"contract_hash": "a" * 64, "methodology_hash": "b" * 64},
        )


def test_frequency_scoped_presence_ignores_an_unrelated_live_connector() -> None:
    profile = profile_document(
        product_scope=["A.DCE"],
        source_scope=["Tiger"],
        frequency_scope=["MIN1"],
        probe=True,
        expanded=False,
        entries=[
            {
                "product": "A.DCE",
                "source": "TigerOSEFuturesMIN1",
                "status": "unavailable",
                "frequency": "MIN1",
            },
            {
                "product": "A.DCE",
                "source": "Tiger",
                "status": "available",
                "frequency": None,
            },
        ],
        as_of=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )
    request = validate_availability_request({
        "products": ["A.DCE"],
        "sources": ["Tiger"],
        "frequencies": ["MIN1"],
        "probe": True,
    })

    _, present = project_availability_evidence(
        profile=profile,
        request=request,
        checkpoint={"contract_hash": "a" * 64, "methodology_hash": "b" * 64},
    )

    assert present is False
