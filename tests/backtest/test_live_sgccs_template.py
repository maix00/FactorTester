from __future__ import annotations

import os
import re
import pytest

from server import create_app
from server.services import page_runtime
from tools.backtest.factors.incremental import compile_streaming_factor


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SGCCS_TEMPLATE") != "1",
    reason="requires the local 18717974771 template and LocalCNFutures data",
)


USERNAME = "18717974771"
TEMPLATE_ID = "1780356047164"
FACTOR_FAMILY = "SgCCS"


def test_live_sgccs_template_restores_and_runs_all_seven_groups() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = USERNAME
        session["_sid"] = "live-sgccs-framework-test"

    page = client.get(f"/single_factor_test?factor={FACTOR_FAMILY}&type=public")
    assert page.status_code == 200
    match = re.search(rb'window\._pageUuid\s*=\s*["\']([^"\']+)', page.data)
    assert match, "single-factor page did not expose page_uuid"
    page_uuid = match.group(1).decode()

    template_response = client.get(
        f"/api/single_factor_setting_templates/{FACTOR_FAMILY}/{TEMPLATE_ID}"
    )
    assert template_response.status_code == 200
    template = template_response.get_json()["template"]
    assert template["name"] == "2026-06-02 07:20:47"
    snapshot = template["snapshot"]

    time_data = snapshot["time_data"]
    response = client.post("/set_time_range", json={
        "factor_family_alias": FACTOR_FAMILY,
        "page_uuid": page_uuid,
        **time_data,
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"]

    response = client.post("/replace_params", json={
        "factor_family_alias": FACTOR_FAMILY,
        "params_list": snapshot["params_list"],
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"]

    tester_ids = {}
    for index, submission in enumerate(snapshot["submissions"]):
        new_id = f"live-sgccs-{index}"
        response = client.post("/submit_selected_products", json={
            "selected_paths": submission["selected_paths"],
            "id_time": new_id,
            "group_name": submission.get("product_group", ""),
            "page_uuid": page_uuid,
        })
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["success"], body
        tester_ids[submission["id"]] = new_id

    groups = _resolve_groups(snapshot["group_settings"]["groups"], tester_ids)
    local = snapshot["local_settings"]
    dates = local["dates"]
    capital = local["initialCapital"]
    calendar = local["calendarFreq"]
    base_payload = {
        "groups": groups,
        "flatCount": len(groups),
        "ls_configs": snapshot["group_settings"].get("lsConfigs", []),
        "page_uuid": page_uuid,
        "factor_family_alias": FACTOR_FAMILY,
        "start_date": dates["startDate"],
        "end_date": dates["endDate"],
        "precision": dates["precision"],
        "timezone": dates["tz"],
        "initial_capital": capital["initialCapital"],
        "auto_group_calendar_freq": calendar["autoGroupCalendarFreq"],
        "group_calendar_freq": calendar["groupCalendarFreq"],
        "_group_factor_params_list": snapshot["params_list"],
        "_group_owner_username": USERNAME,
    }
    profiles = {
        "baseline": {
            "allocation_policy": "equal_notional",
            "fee_mode": "none",
            "margin_mode": "none",
            "liquidity_mode": "infinite",
        },
        "execution_plugins": {
            "allocation_policy": "inverse_volatility",
            "volatility_lookback": 20,
            "volatility_warmup": "equal_notional",
            "fee_mode": "custom",
            "custom_fee_rate": 0.000001,
            "margin_mode": "market",
            "collateral_fraction": 1.0,
            "liquidity_mode": "volume_participation",
            "participation_rate": 0.1,
            "slippage_mode": "fixed_bps",
            "slippage_bps": 0.1,
        },
    }
    selected_profile = os.environ.get("LIVE_SGCCS_PROFILE")
    if selected_profile:
        profiles = {selected_profile: profiles[selected_profile]}
    results = {}
    for profile, profile_settings in profiles.items():
        results[profile] = {}
        for engine in ("native", "backtrader", "qlib", "zipline"):
            response = client.post("/run_group_test", json={
                **base_payload,
                "backtest_settings": {
                    "application": "group_test",
                    "local_values": {
                        "engine": engine,
                        "factor_mode": "precomputed",
                        "rebalance_mode": "on_factor_signal",
                        "initial_capital": capital["initialCapital"],
                        **profile_settings,
                    },
                    "group_values": {},
                },
            })
            body = response.get_json()
            assert response.status_code == 200, {
                "profile": profile, "engine": engine, "body": body,
            }
            assert body["success"], body
            assert body["simulation_count"] == 1
            assert len(body["groups"]) == 7
            assert len(body["metrics"]) == 7
            assert body["engine_result"]["engine"] == engine
            results[profile][engine] = body

    tester = page_runtime.get_factor_tester(
        "live-sgccs-0", caller="live-framework-test", page_uuid=page_uuid
    )
    factor = tester.resolve_factor("SgCCS|N:2m|$F:1m|$Rev")
    assert factor is not None
    compile_streaming_factor(
        factor._source_expr,
        tuple(str(product.name) for product in tester.products),
        source_freq=factor._source_freq,
    )
    for profile, profile_results in results.items():
        traces = {
            engine: {
                group["group_id"]: group["target_trace"] for group in body["groups"]
            }
            for engine, body in profile_results.items()
        }
        assert traces["native"] == traces["backtrader"] == traces["qlib"] == traces["zipline"], profile

    latest = results[next(reversed(results))]["zipline"]
    first_group = latest["groups"][0]
    detail = client.post("/get_group_detail", json={
        "submission_id": first_group["submission_id"],
        "group_index": first_group["group_index"],
        "page_uuid": page_uuid,
    })
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["detail"]["return_series"]

    ranking = client.post("/get_group_ranking_detail", json={
        "submission_id": first_group["submission_id"],
        "page_uuid": page_uuid,
    })
    assert ranking.status_code == 200, ranking.get_json()
    assert ranking.get_json()["detail"]["adjacent_spreads"]

    snapshot_response = client.post("/get_group_snapshot", json={
        "submission_id": first_group["submission_id"],
        "timestamp_ms": first_group["timestamps"][-1],
        "page_uuid": page_uuid,
    })
    assert snapshot_response.status_code == 200, snapshot_response.get_json()
    snapshot_body = snapshot_response.get_json()
    assert snapshot_body["event_cursor"]
    assert [matrix["key"] for matrix in snapshot_body["matrices"]] == [
        "positions", "targets",
    ]


def _resolve_groups(groups: list[dict], tester_ids: dict[str, str]) -> list[dict]:
    by_id = {group["id"]: group for group in groups}
    result = []
    inherited = (
        "testerId", "factorAlias", "splitCount", "groupIndex", "isAllGroups",
        "startDate", "endDate",
    )
    for original in groups:
        group = dict(original)
        parent = by_id.get(group.get("parentId"))
        while parent is not None:
            for key in inherited:
                if group.get(key) in (None, "") and parent.get(key) not in (None, ""):
                    group[key] = parent[key]
            parent = by_id.get(parent.get("parentId"))
        group["testerId"] = tester_ids[group["testerId"]]
        result.append(group)
    return result
