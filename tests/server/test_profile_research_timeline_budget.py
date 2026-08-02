from __future__ import annotations

import orjson

from server.services.research_graph.profile_research_projection.refs import (
    MAX_PROJECTION_BYTES,
)
from tests.server.test_profile_research_projection import (
    _evidence,
    _seed,
    _service,
)
from tools.data.sqlite.db import connect_sqlite


_FACTOR_REF = (
    "factor-family:v1:profile-maxa:cGF0aA:U2dDUFNWb2w:"
    + "a" * 40 + ":" + "b" * 40
)


def _large_transition_evidence(index: int) -> dict:
    evidence = _evidence(index)
    evidence["report_submission"] = {
        "schema_version": 1,
        "fragment_hash": "f" * 64,
        "items": [
            {
                "item_hash": f"{item_index:064x}",
                "report_requirement_id": (
                    "trial_design_validity."
                    f"requirement_{item_index:02d}"
                ),
                "subject_ref": _FACTOR_REF,
                "content_kind": "table",
            }
            for item_index in range(16)
        ],
    }
    return evidence


def test_work_package_timeline_pages_large_steps_without_losing_rows(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "large-profile-research-timeline.sqlite"
    trace_count = 51
    _seed(path, branch_count=1, trace_count=trace_count)
    with connect_sqlite(path) as conn:
        conn.executemany(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id=?",
            [
                (
                    orjson.dumps(_large_transition_evidence(index)).decode(),
                    f"trace-{index:06d}",
                )
                for index in range(trace_count)
            ],
        )
    service = _service(path, monkeypatch)

    pages: list[dict] = []
    after = ""
    while True:
        page = service.list_work_package_timeline(
            owner="alice",
            work_package_ref="work-package:instance-a",
            branch_id="branch-0000",
            limit=50,
            after=after,
        )
        pages.append(page)
        assert len(orjson.dumps(page)) <= MAX_PROJECTION_BYTES
        if page["next_cursor"] is None:
            break
        after = page["next_cursor"]

    # UI/audit projections have a generous ceiling and therefore should not
    # manufacture extra HTTP pages for this ordinary 50-step history.
    assert len(pages[0]["items"]) == 50
    assert pages[0]["next_cursor"] is not None
    first_page_last_index = int(
        pages[0]["items"][-1]["step_ref"].rsplit("-", 1)[1]
    )
    assert pages[1]["items"][0]["step_ref"] == (
        f"trace:trace-{first_page_last_index - 1:06d}"
    )
    assert [
        item["step_ref"]
        for page in pages
        for item in page["items"]
    ] == [
        f"trace:trace-{index:06d}"
        for index in reversed(range(trace_count))
    ]
