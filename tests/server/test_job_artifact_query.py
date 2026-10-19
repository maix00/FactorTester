from __future__ import annotations

from server.manager.services.job_artifact_query import query_artifact_value


def test_table_query_returns_only_requested_page() -> None:
    value = {
        "schema_version": 1,
        "artifact_kind": "order_detail",
        "columns": ["strategy", "order_id"],
        "rows": [
            {"strategy": "A", "order_id": f"order-{index}"}
            for index in range(105)
        ],
    }

    result = query_artifact_value(
        value, {"mode": "table", "page": 3, "page_size": 20},
    )

    assert result["query_mode"] == "table"
    assert result["page"] == 3
    assert result["page_size"] == 20
    assert result["total"] == 105
    assert result["columns"] == ["strategy", "order_id"]
    assert [row["order_id"] for row in result["rows"]] == [
        f"order-{index}" for index in range(40, 60)
    ]


def test_table_query_applies_filters_and_returns_facets_and_distinct_relations() -> None:
    value = {"rows": [
        {"strategy": "A", "account_id": "a1", "cash_pool_id": "p1"},
        {"strategy": "A", "account_id": "a2", "cash_pool_id": "p1"},
        {"strategy": "B", "account_id": "b1", "cash_pool_id": "p2"},
    ]}

    result = query_artifact_value(value, {
        "mode": "table",
        "filters": {"strategy": {
            "fields": ["strategy_id", "strategy"], "values": ["A"],
        }},
        "facets": {
            "account": ["account_id", "account"],
            "cash_pool": ["cash_pool_id", "cash_pool"],
        },
        "distinct": {"relations": {
            "strategy": ["strategy_id", "strategy"],
            "account": ["account_id", "account"],
            "cash_pool": ["cash_pool_id", "cash_pool"],
        }},
    })

    assert result["total"] == 2
    assert result["facets"] == {"account": ["a1", "a2"], "cash_pool": ["p1"]}
    assert result["distinct"]["relations"] == [
        {"strategy": "A", "account": "a1", "cash_pool": "p1"},
        {"strategy": "A", "account": "a2", "cash_pool": "p1"},
    ]


def test_series_query_downsamples_initial_view_and_refines_zoom_window() -> None:
    value = {
        "schema_version": 1,
        "artifact_kind": "equity_curve",
        "series": [{
            "label": "A",
            "timestamps": list(range(10_000)),
            "values": [float(index) for index in range(10_000)],
            "drawdown": [-(index % 100) / 100 for index in range(10_000)],
        }],
    }

    initial = query_artifact_value(
        value, {"mode": "series", "max_points": 600},
    )
    zoomed = query_artifact_value(value, {
        "mode": "series", "from": 4_000, "to": 4_199,
        "max_points": 600,
    })

    assert initial["query_mode"] == "series"
    assert len(initial["series"][0]["timestamps"]) <= 600
    assert len(initial["series"][0]["values"]) == len(
        initial["series"][0]["timestamps"],
    )
    assert len(initial["series"][0]["drawdown"]) == len(
        initial["series"][0]["timestamps"],
    )
    assert zoomed["series"][0]["timestamps"] == list(range(4_000, 4_200))
    assert zoomed["sampling"]["source_points"] == 10_000
    assert zoomed["sampling"]["visible_points"] == 200


def test_time_rows_query_filters_fields_range_and_point_count() -> None:
    value = {
        "schema_version": 1,
        "artifact_kind": "metrics_over_time",
        "rows": [
            {
                "series": strategy,
                "timestamp": timestamp,
                "annual_return": timestamp / 100,
                "unused": "large-field",
            }
            for strategy in ("A", "B")
            for timestamp in range(1_000)
        ],
    }

    result = query_artifact_value(value, {
        "mode": "time_rows", "from": 200, "to": 699,
        "max_points": 120,
        "fields": ["series", "timestamp", "annual_return"],
    })

    assert result["query_mode"] == "time_rows"
    assert len(result["rows"]) <= 240
    assert {row["series"] for row in result["rows"]} == {"A", "B"}
    assert all(200 <= row["timestamp"] <= 699 for row in result["rows"])
    assert all(
        set(row) == {"series", "timestamp", "annual_return"}
        for row in result["rows"]
    )


def test_time_rows_filters_instrument_and_strategy_before_sampling() -> None:
    rows = [
        {"timestamp": index, "instrument": "AU.SHF", "strategy": "chosen", "price": index}
        for index in range(100)
    ] + [
        {"timestamp": index, "instrument": "RB.SHF", "strategy": "chosen", "price": index}
        for index in range(100)
    ] + [
        {"timestamp": index, "instrument": "AU.SHF", "strategy": "other", "price": index}
        for index in range(100)
    ] + [{"timestamp": 50, "strategy": "chosen", "price": 50}]
    result = query_artifact_value({"rows": rows}, {
        "mode": "time_rows", "max_points": 20,
        "filters": {
            "instrument": {"fields": ["instrument", "product"], "values": ["AU.SHF"]},
            "strategy": {"fields": ["strategy_id", "strategy"], "values": ["chosen"]},
        },
    })
    assert result["sampling"]["source_rows"] == len(rows)
    assert result["sampling"]["visible_rows"] == 100
    assert len(result["rows"]) <= 20
    assert all(row["instrument"] == "AU.SHF" and row["strategy"] == "chosen"
               for row in result["rows"])


def test_time_rows_uses_native_order_submission_time() -> None:
    rows = [
        {"submitted_at": "2025-04-10T14:30:00+08:00", "product": "SHFE|F|AU|2506",
         "strategy": "screen_AU", "order_id": "first"},
        {"submitted_at": "2025-04-11T14:30:00+08:00", "product": "SHFE|F|AU|2506",
         "strategy": "screen_AU", "order_id": "later"},
    ]
    result = query_artifact_value({"rows": rows}, {
        "mode": "time_rows", "from": 1744266600000, "to": 1744266600000,
        "max_points": 20,
        "fields": ["submitted_at", "product", "strategy", "order_id"],
        "filters": {"product": {
            "fields": ["contract_uid", "instrument", "product"],
            "values": ["SHFE|F|AU|2506"],
        }},
    })
    assert [row["order_id"] for row in result["rows"]] == ["first"]


def test_time_rows_retains_order_with_later_lifecycle_phase() -> None:
    submitted = 1_744_266_600_000
    later = submitted + 86_400_000
    rows = [{
        "submitted_at": submitted, "product": "SHFE|F|AU|2506",
        "strategy": "screen_AU", "order_id": "first",
        "lifecycle": [
            {"kind": "submitted", "timestamp": submitted},
            {"kind": "action", "action": "cancel", "timestamp": later},
        ],
    }]
    result = query_artifact_value({"rows": rows}, {
        "mode": "time_rows", "from": later - 1000, "to": later + 1000,
        "fields": ["submitted_at", "product", "order_id", "lifecycle"],
        "filters": {"product": {
            "fields": ["product"], "values": ["SHFE|F|AU|2506"],
        }},
    })
    assert [row["order_id"] for row in result["rows"]] == ["first"]
    assert result["rows"][0]["lifecycle"][1]["action"] == "cancel"


def test_time_rows_matches_native_nanosecond_fills_by_order_id() -> None:
    rows = [
        {"timestamp": 1744266660000000000, "order_id": "selected", "fill_id": "one"},
        {"timestamp": 1744266660000000000, "order_id": "other", "fill_id": "two"},
    ]
    result = query_artifact_value({"rows": rows}, {
        "mode": "time_rows", "from": 1744266600000, "to": 1744266720000,
        "filters": {"order": {"fields": ["order_id"], "values": ["selected"]}},
    })
    assert [row["fill_id"] for row in result["rows"]] == ["one"]


def test_chart_range_uses_milliseconds_for_second_epoch_artifacts() -> None:
    value = {"series": [{
        "label": "A",
        "timestamps": [1_700_000_000, 1_700_000_060],
        "values": [100, 101],
    }]}

    result = query_artifact_value(value, {
        "mode": "series",
        "from": 1_700_000_000_000,
        "to": 1_700_000_030_000,
        "max_points": 20,
    })

    assert result["series"][0]["timestamps"] == [1_700_000_000]
    assert result["series"][0]["values"] == [100]
