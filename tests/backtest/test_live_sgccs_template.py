from __future__ import annotations

import json
import os
import re
import uuid
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


def _post_group_stream_result(client, payload: dict) -> tuple[int, dict]:
    response = client.post("/run_group_test_stream", json={
        **payload,
        "run_token": uuid.uuid4().hex,
    })
    raw = response.get_data(as_text=True)
    result = None
    current_event = ""
    for line in raw.splitlines():
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: ") and current_event in {"result", "error"}:
            result = json.loads(line[6:])
    assert result is not None, raw[-2000:]
    return response.status_code, result


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

    local_values = snapshot["local_settings"]
    assert {
        "start_date": local_values["start_date"],
        "end_date": local_values["end_date"],
        "start_time": local_values["start_time"],
        "end_time": local_values["end_time"],
    } == {
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "start_time": "09:00",
        "end_time": "15:00",
    }
    assert "time_data" not in snapshot
    assert "backendBacktestSettings" not in snapshot["local_settings"]
    assert "dates" not in snapshot["local_settings"]
    start_date = os.environ.get("LIVE_SGCCS_START_DATE", local_values["start_date"])
    end_date = os.environ.get("LIVE_SGCCS_END_DATE", local_values["end_date"])
    start_time = os.environ.get("LIVE_SGCCS_START_TIME", local_values["start_time"])
    end_time = os.environ.get("LIVE_SGCCS_END_TIME", local_values["end_time"])

    response = client.post("/set_time_range", json={
        "factor_family_alias": FACTOR_FAMILY,
        "page_uuid": page_uuid,
        "start_date": start_date,
        "start_time": start_time,
        "end_date": end_date,
        "end_time": end_time,
        "timezone": local_values.get("timezone", "Asia/Shanghai"),
        "time_precision": local_values.get("time_precision", "exact"),
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
    long_short_configs = _resolve_ls_configs(
        snapshot["group_settings"].get("lsConfigs", []),
        groups,
    )
    if os.environ.get("LIVE_SGCCS_LONG_SHORT") == "1":
        if not long_short_configs:
            long_group, short_group = _default_ls_pair(groups)
            long_short_configs = [_runtime_ls_config(long_group, short_group)]
    base_payload = {
        "groups": groups,
        "flatCount": len(groups),
        "ls_configs": long_short_configs,
        "page_uuid": page_uuid,
        "factor_family_alias": FACTOR_FAMILY,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "precision": local_values.get("time_precision", "exact"),
        "timezone": local_values.get("timezone", "Asia/Shanghai"),
        "initial_capital": local_values.get("initial_capital", 100000000),
        "auto_group_calendar_freq": local_values.get("calendar_frequency", "auto") == "auto",
        "group_calendar_freq": None if local_values.get("calendar_frequency", "auto") == "auto" else local_values["calendar_frequency"],
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
            profile_groups = [{**group, **profile_settings} for group in groups]
            status_code, body = _post_group_stream_result(client, {
                **base_payload,
                "groups": profile_groups,
                "engine": engine,
                "factor_mode": "precomputed",
                "rebalance_trigger": "on_factor_signal",
                "initial_capital": local_values.get("initial_capital", 100000000),
            })
            assert status_code == 200, {
                "profile": profile, "engine": engine, "body": body,
            }
            assert body["success"], body
            assert body["simulation_count"] == 1
            expected_strategy_count = 7 + len(long_short_configs)
            assert len(body["groups"]) == expected_strategy_count
            assert len(body["metrics"]) == expected_strategy_count
            assert body["cross_entry_ls_count"] == len(long_short_configs)
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
        equity_curves = {
            engine: {
                group["group_id"]: group["total_equity"] for group in body["groups"]
            }
            for engine, body in profile_results.items()
        }
        assert equity_curves["native"] == equity_curves["backtrader"] == equity_curves["qlib"] == equity_curves["zipline"], profile
        final_values = {
            engine: {
                group["group_id"]: group["total_equity"][-1] for group in body["groups"]
            }
            for engine, body in profile_results.items()
        }
        assert final_values["native"] == final_values["backtrader"] == final_values["qlib"] == final_values["zipline"], profile
        if long_short_configs:
            ls_group = next(
                group for group in profile_results["native"]["groups"]
                if group["is_ls"]
            )
            assert any(
                any(weight > 0 for weight in target.values())
                and any(weight < 0 for weight in target.values())
                for target in ls_group["target_trace"].values()
            )

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
        "positions_contracts", "positions_products",
        "targets_contracts", "targets_products",
    ]
    assert snapshot_body["event_type"] in {"FILL", "REJECT"}


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


def _resolve_ls_configs(configs: list[dict], groups: list[dict]) -> list[dict]:
    by_id = {str(group["id"]): group for group in groups}
    resolved = []
    for config in configs or []:
        long_id = str(config.get("longGroupId") or "")
        short_id = str(config.get("shortGroupId") or "")
        if not long_id or not short_id:
            resolved.append(config)
            continue
        resolved.append(_runtime_ls_config(by_id[long_id], by_id[short_id], config))
    return resolved


def _default_ls_pair(groups: list[dict]) -> tuple[dict, dict]:
    flat_groups = [
        group for group in groups
        if not group.get("parentId") and group.get("groupIndex") is not None
    ]
    long_group = next(group for group in flat_groups if group.get("groupIndex") == 1)
    short_group = next(group for group in flat_groups if group.get("groupIndex") == 5)
    return long_group, short_group


def _runtime_ls_config(long_group: dict, short_group: dict, source: dict | None = None) -> dict:
    source = source or {}
    return {
        "id": source.get("id") or "live-ls-1",
        "name": source.get("name") or f"SgCCS {long_group.get('shortAlias', '第1组')}/{short_group.get('shortAlias', '第5组')}",
        "long": [{"group_id": long_group["id"], "weight": 1.0}],
        "short": [{"group_id": short_group["id"], "weight": 1.0}],
    }
