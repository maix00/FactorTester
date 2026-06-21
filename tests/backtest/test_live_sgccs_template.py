from __future__ import annotations

import os
import re
import math

import pytest

from server import create_app
from server.services import page_runtime
from tools.backtest.strategies.group_worker import build_group_target_weight_payload
from tools.backtest.workers import EngineWorkerDispatcher, WorkerRequest


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
    response = client.post("/run_group_test", json={
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
    })
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["success"], body
    assert body["simulation_count"] == 1
    assert len(body["groups"]) == 7
    assert len(body["metrics"]) == 7

    tester = page_runtime.get_factor_tester("live-sgccs-0", caller="live-framework-test")
    factor = tester.resolve_factor("SgCCS|N:2m|$F:1m|$Rev")
    assert factor is not None
    group_result = tester._get_result(factor).group_result
    assert group_result is not None
    strategy_ids = [group["shortAlias"] for group in groups]
    payload = build_group_target_weight_payload(
        group_result,
        strategy_ids=strategy_ids,
        rebalance_modes=[group["rebalanceMode"] for group in groups],
        initial_cash=capital["initialCapital"],
    )
    assert len(payload["strategies"]) == 7
    assert all(
        abs(sum(weights.values()) - 1.0) < 1e-12
        for strategy in payload["strategies"]
        for weights in strategy["targets"].values()
        if weights
    )

    dispatcher = EngineWorkerDispatcher()
    for engine in ("backtrader", "qlib", "zipline"):
        worker_result = dispatcher.dispatch(
            WorkerRequest(f"live-sgccs-{engine}", engine, "run_target_weights", payload),
            timeout_seconds=300,
        ).result
        assert set(worker_result["portfolios"]) == set(strategy_ids)
        assert all(
            math.isfinite(portfolio["final_value"])
            and portfolio["final_value"] > 0
            for portfolio in worker_result["portfolios"].values()
        )


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
