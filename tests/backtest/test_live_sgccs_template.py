from __future__ import annotations

import json
import os
import re
import uuid
import pytest

from server import create_app
from server.services import page_runtime
from tools.testers.backtest.engines.factors.incremental import compile_streaming_factor


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
    # Templates now store factor_candidates.  Push each candidate through the
    # same endpoint the frontend uses so page_factors becomes the single source.
    for params_row in _template_factor_params(snapshot):
        resp = client.post("/add_factor_by_params", json={
            "factor_family_alias": FACTOR_FAMILY,
            "params": params_row,
            "page_uuid": page_uuid,
        })
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"]

    groups = _resolve_groups(snapshot["group_settings"]["groups"], {})
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
        "ls_configs": long_short_configs,
        "page_uuid": page_uuid,
        "factor_family_alias": FACTOR_FAMILY,
        "local_settings": {
            **local_values,
            "engine": "native",
            "factor_mode": "precomputed",
            "rebalance_trigger": "on_factor_signal",
        },
        "_runtime_window": {
            "start_date": local_values["start_date"],
            "end_date": local_values["end_date"],
            "start_time": local_values["start_time"],
            "end_time": local_values["end_time"],
            "time_precision": local_values.get("time_precision", "exact"),
            "timezone": local_values.get("timezone", "Asia/Shanghai"),
        },
        "auto_group_calendar_freq": local_values.get("calendar_frequency", "auto") == "auto",
        "group_calendar_freq": None if local_values.get("calendar_frequency", "auto") == "auto" else local_values["calendar_frequency"],
        "_group_owner_username": USERNAME,
    }
    profiles = {
        "baseline": {
            "allocation_policy": "equal_notional",
            "engine_mode": "basic",
            "fee_mode": "zero",
            "margin_mode": "none",
            "liquidity_mode": "infinite",
        },
        "execution_plugins": {
            "allocation_policy": "inverse_volatility",
            "volatility_lookback": 20,
            "volatility_warmup": "equal_notional",
            "engine_mode": "custom",
            "fee_mode": "fixed",
            "fixed_fee_rate": 0.000001,
            "margin_mode": "auto",
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
                "local_settings": {
                    **base_payload["local_settings"],
                    "engine": engine,
                    "factor_mode": "precomputed",
                    "rebalance_trigger": "on_factor_signal",
                },
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

    testers = page_runtime.iter_page_objects(page_runtime.FACTOR_TESTER, page_uuid=page_uuid)
    tester = next(
        (
            item for item in testers
            if item.resolve_factor("SgCCS|N:2m|$F:1m|$Rev") is not None
        ),
        None,
    )
    assert tester is not None, [getattr(item, "alias", "?") for item in testers]
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
                strategy["strategy_id"]: strategy["target_trace_checksum"]
                for strategy in body["engine_result"]["comparison"]["strategies"]
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
        # Engines accumulate fees/slippage in different float summation orders, so
        # the shared 2-decimal display rounding can land a cent apart on a ~1e8
        # notional curve even though the underlying signal (target_trace_checksum
        # above) is bit-identical. Compare with a relative tolerance instead of
        # exact equality.
        reference_curves = equity_curves["native"]
        for engine in ("backtrader", "qlib", "zipline"):
            for group_id, curve in equity_curves[engine].items():
                expected = reference_curves[group_id]
                assert len(curve) == len(expected), (profile, engine, group_id)
                for actual_value, expected_value in zip(curve, expected):
                    assert actual_value == pytest.approx(expected_value, rel=1e-6, abs=0.05), (
                        profile, engine, group_id,
                    )
        final_values = {
            engine: {
                group["group_id"]: group["total_equity"][-1] for group in body["groups"]
            }
            for engine, body in profile_results.items()
        }
        for engine in ("backtrader", "qlib", "zipline"):
            for group_id, value in final_values[engine].items():
                assert value == pytest.approx(final_values["native"][group_id], rel=1e-6, abs=0.05), (
                    profile, engine, group_id,
                )
        if long_short_configs:
            ls_group = next(
                group for group in profile_results["native"]["groups"]
                if group["is_ls"]
            )
            ls_snapshot = client.post("/get_group_snapshot", json={
                "product_path_selection_id": ls_group["product_path_selection_id"],
                "timestamp_ms": ls_group["timestamps"][-1],
                "page_uuid": page_uuid,
            })
            assert ls_snapshot.status_code == 200, ls_snapshot.get_json()
            ls_snapshot_body = ls_snapshot.get_json()
            targets_products = next(
                matrix for matrix in ls_snapshot_body["matrices"]
                if matrix["key"] == "targets_products"
            )
            column_index = next(
                index for index, column in enumerate(targets_products["columns"])
                if column["label"] == ls_group["name"]
            )
            ls_weights = []
            for row in targets_products["cells"]:
                reason = row[column_index].get("open_reason")
                match = reason and re.search(r"(-?\d[\d.]*)%", reason)
                if match:
                    ls_weights.append(float(match.group(1)))
            assert any(weight > 0 for weight in ls_weights), profile
            assert any(weight < 0 for weight in ls_weights), profile

    latest = results[next(reversed(results))]["zipline"]
    first_group = latest["groups"][0]
    detail = client.post("/get_group_detail", json={
        "product_path_selection_id": first_group["product_path_selection_id"],
        "group_index": first_group["group_index"],
        "page_uuid": page_uuid,
    })
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["detail"]["return_series"]

    ranking = client.post("/get_group_ranking_detail", json={
        "product_path_selection_id": first_group["product_path_selection_id"],
        "page_uuid": page_uuid,
    })
    assert ranking.status_code == 200, ranking.get_json()
    assert ranking.get_json()["detail"]["adjacent_spreads"]

    snapshot_response = client.post("/get_group_snapshot", json={
        "product_path_selection_id": first_group["product_path_selection_id"],
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


def test_live_sgccs_template_equal_notional_and_equal_risk_diverge_on_real_data() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = USERNAME
        session["_sid"] = "live-sgccs-allocation-diff"

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

    for params_row in _template_factor_params(snapshot):
        resp = client.post("/add_factor_by_params", json={
            "factor_family_alias": FACTOR_FAMILY,
            "params": params_row,
            "page_uuid": page_uuid,
        })
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["success"]

    groups = [
        group for group in _resolve_groups(snapshot["group_settings"]["groups"], {})
        if not group.get("parentId") and int(group.get("groupIndex") or 0) == 1
    ]
    assert groups
    group = groups[0]
    base_payload = {
        "groups": [group],
        "ls_configs": [],
        "page_uuid": page_uuid,
        "factor_family_alias": FACTOR_FAMILY,
        "local_settings": {
            **local_values,
            "engine": "native",
            "factor_mode": "precomputed",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
            "execution_timing": "same_bar",
            "engine_mode": "basic",
            "fee_mode": "zero",
            "margin_mode": "none",
        },
        "_runtime_window": {
            "start_date": local_values["start_date"],
            "end_date": local_values["end_date"],
            "start_time": local_values["start_time"],
            "end_time": local_values["end_time"],
            "time_precision": local_values.get("time_precision", "exact"),
            "timezone": local_values.get("timezone", "Asia/Shanghai"),
        },
        "auto_group_calendar_freq": local_values.get("calendar_frequency", "auto") == "auto",
        "group_calendar_freq": None if local_values.get("calendar_frequency", "auto") == "auto" else local_values["calendar_frequency"],
    }
    profiles = {
        "equal_notional": {"allocation_policy": "equal_notional"},
        "equal_risk": {
            "allocation_policy": "inverse_volatility",
            "volatility_lookback": 20,
            "volatility_warmup": "equal_notional",
        },
    }
    results = {}
    default_group = {
        key: value for key, value in group.items()
        if key not in {
            "allocation_policy",
            "volatility_lookback",
            "volatility_warmup",
            "rebalance_trigger",
            "position_policy",
            "execution_timing",
            "execution_price_basis",
            "execution_delay_bars",
        }
    }
    default_group = {**default_group, "liquidity_mode": "infinite"}
    status_code, default_body = _post_group_stream_result(
        client, {**base_payload, "groups": [default_group]}
    )
    assert status_code == 200, {"body": default_body}
    assert default_body["success"], default_body
    defaults_by_key = {
        item["setting_key"]: item
        for item in default_body.get("silent_default_settings") or []
    }
    assert defaults_by_key["allocation_policy"]["value"] == "inverse_volatility"
    assert defaults_by_key["allocation_policy"]["value_label"] == "等风险（波动率倒数）"

    body_by_profile = {}
    for name, overrides in profiles.items():
        payload = {**base_payload, "groups": [{**group, "liquidity_mode": "infinite", **overrides}]}
        status_code, body = _post_group_stream_result(client, payload)
        assert status_code == 200, {"profile": name, "body": body}
        assert body["success"], body
        body_by_profile[name] = body
        results[name] = body["groups"][0]

    notional = results["equal_notional"]
    risk = results["equal_risk"]
    notional_checksum = next(
        strategy["target_trace_checksum"]
        for strategy in body_by_profile["equal_notional"]["engine_result"]["comparison"]["strategies"]
        if strategy["strategy_id"] == notional["group_id"]
    )
    risk_checksum = next(
        strategy["target_trace_checksum"]
        for strategy in body_by_profile["equal_risk"]["engine_result"]["comparison"]["strategies"]
        if strategy["strategy_id"] == risk["group_id"]
    )
    assert notional_checksum != risk_checksum
    assert notional["total_equity"] != risk["total_equity"]
    assert notional["total_equity"][-1] != risk["total_equity"][-1]


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
        if group.get("testerId") in tester_ids:
            group["testerId"] = tester_ids[group["testerId"]]
        result.append(group)
    return result


def _template_factor_params(snapshot: dict) -> list[dict]:
    if isinstance(snapshot.get("factor_candidates"), list):
        return [
            dict(candidate.get("params") or {})
            for candidate in snapshot["factor_candidates"]
            if isinstance(candidate, dict) and isinstance(candidate.get("params"), dict)
        ]
    return list(snapshot.get("params_list") or [])


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
