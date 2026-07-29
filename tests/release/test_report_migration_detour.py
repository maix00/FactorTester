from tmp.report_migration.detour_entries import (
    CURRENT_OPEN_GAP,
    TRANSITIONS,
)
from tmp.report_migration.hierarchy_plan import DETOUR_CHILDREN
from tmp.report_migration.hierarchy_plan import (
    HYPOTHESIS_CHAPTER,
    hierarchy_operations,
)


def test_capability_detour_preserves_exact_five_transition_records() -> None:
    assert [
        (item["timestamp"], item["trace_id"])
        for item in TRANSITIONS
    ] == [
        (
            "2026-07-28 11:31:41.743602 Asia/Taipei",
            "2617faa42d3945489aa3cf1381528f85",
        ),
        (
            "2026-07-28 11:54:12.828754 Asia/Taipei",
            "0b86dc02e0bb4185b86317e0efb99662",
        ),
        (
            "2026-07-28 11:55:33.516923 Asia/Taipei",
            "be7bdbb1dbfb4d5db5388faddfc8c59d",
        ),
        (
            "2026-07-28 12:12:16.664466 Asia/Taipei",
            "dbefa399a69344618ced3f248eab5d7b",
        ),
        (
            "2026-07-28 12:12:38.513917 Asia/Taipei",
            "8e17cce63d3b440081b023c3fefafcfd",
        ),
    ]
    assert TRANSITIONS[0]["from_node"] == "hypothesis_preregistration"
    assert TRANSITIONS[-1]["to_node"] == "capability_gap"
    assert CURRENT_OPEN_GAP["missing_capability"] == (
        "research-evidence.graph-admission-binding"
    )


def test_detour_is_one_ordered_lifecycle_special() -> None:
    assert DETOUR_CHILDREN == (
        "profile-screen-alias-capability-gap",
        "capability-detour-transition-1",
        "profile-screen-alias-capability-resolution-evidence",
        "maxa-profile-screen-recovery-acceptance",
        "capability-detour-transition-2",
        "cnfutures-day-pit-provenance-gap",
        "capability-detour-transition-3",
        "local-cnfutures-day-pit-reusable-evidence-admission",
        "capability-detour-transition-4",
        "capability-detour-transition-5",
        "capability-detour-current-open-gap",
    )
    operations = hierarchy_operations()
    detour_move = next(
        item for item in operations
        if item["op"] == "move"
        and item["component_id"] == "profile-screen-alias-capability-resolution"
    )
    assert detour_move["parent_id"] == HYPOTHESIS_CHAPTER
    assert not any(
        item.get("component_id") == "section-capability-detour"
        for item in operations
    )
