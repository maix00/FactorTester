from __future__ import annotations

from flask import Flask
import pytest

import settings as Settings
from server.modules.single_factor_test import research_jobs, sft_bp
import server.modules.shared.submission_helpers  # noqa: F401 - product resolver
from server.services import factor_registry
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam
from server.services.run_input_inspection import instantiate_factor_metadata


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "research-jobs.sqlite")
    factor_sources = {
        family: f"""
from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef

class {family}(FactorFamily):
    @staticmethod
    def factor_expr():
        return ColumnRef(DataColumn.CLOSE)
"""
        for family in ("MmRet", "MmMADevRat")
    }
    monkeypatch.setattr(
        factor_registry,
        "load_public_factor_source",
        lambda factor_id: factor_sources.get(str(factor_id)),
    )
    monkeypatch.setattr(
        factor_registry, "factor_from_alias", lambda alias, **_kwargs: alias,
    )
    monkeypatch.setattr(
        research_jobs,
        "_capability_plans",
        lambda prepared, owner: [
            {"kind": kind, "resolved": {"data_requirements": []}}
            for kind in prepared["analyses"]
        ],
    )
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["username"] = "alice"
    return test_client


def _create_workspace(client):
    factors = []
    for family in ("MmRet", "MmMADevRat"):
        metadata = instantiate_factor_metadata(
            factor_registry.get_factor_family_instance(f"public:{family}"), {},
        )
        factors.append(freeze_factor_identity(
            owner_ref="public",
            family_alias=family,
            factor_alias=metadata["factor_alias"],
            family_formula_fingerprint=metadata["family_formula_fingerprint"],
            self_formula_fingerprint=metadata["self_formula_fingerprint"],
            params=metadata["normalized_params"],
        ))
    response = client.post("/api/workspaces", json={
        "title": "RunSpec field contract",
        "factors": factors,
    })
    assert response.status_code == 201
    return response.get_json()["workspace"]


def test_factor_metadata_uses_template_latex_and_keeps_resolved_formula_separate():
    class AroonMetadataFamily(FactorFamily):
        @staticmethod
        def factor_expr():
            high = DataColumnParam("H", default_value="HA")
            window = WindowParam("N", default_value="25d")
            rolling = high.rolling(window)
            highest = rolling.argmax_raw().as_intermediate("最高价位置")
            bars = rolling.bars
            days_since_high = (bars - 1.0 - highest).as_intermediate("距最高价天数")
            return ((bars - days_since_high) / bars * 100.0).as_intermediate("Aroon上轨")

    metadata = instantiate_factor_metadata(AroonMetadataFamily(), {"N": "25d"})

    assert r"\textcolor{red}{N}" in metadata["math_expr"]
    assert r"\mathrm{Bars}\left(\textcolor{red}{N}\right)" in metadata["math_expr"]
    assert "25 days 00:00:00" not in metadata["math_expr"]
    assert r"25\,\mathrm{d}" in metadata["resolved_math_expr"]


def _update(client, workspace) -> None:
    shared = dict(workspace["configuration"]["payload"]["shared"])
    factor_ref = shared["factors"][0]["ref"]
    payload = {
        "schema_version": 3,
        "shared": shared,
        "analyses": {
            "ic": {
                "execution": {"settings": {}},
                "factor_configs": [{"N": "10d"}],
                "product_paths": ["core8_path"],
            },
            "backtest": {
                "execution": {"settings": {
                    "start_date": "2024-01-02",
                    "end_date": "2024-02-02",
                    "account_currency": "USD",
                    "base_currency": "CNY",
                }},
                "groups": [{
                    "id": "A1", "name": "A1", "splitCount": 5, "groupIndex": 1,
                    "factor_candidate_refs": [factor_ref],
                    "product_path_selection_id": "core8",
                }],
                "product_selections": {
                    "core8": {"id": "core8", "selected_paths": ["core8_path"]},
                },
            },
            "factor_evaluation": {"factor_alias": "MmRet|P:CA|N:10d|$F:1d"},
            "factor_type_analysis": {"factor_alias": "MmRet|P:CA|N:10d|$F:1d"},
        },
        "ui": {"selected_tab": "ic"},
    }
    response = client.put(
        f"/api/workspaces/{workspace['workspace_id']}/configuration",
        json={
            "expected_revision": workspace["configuration"]["revision"],
            "payload": payload,
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    workspace["configuration"] = response.get_json()["configuration"]


def _run_control_keys(application_name: str) -> set[str]:
    from tools.testers.settings import backtest_setting_registry

    return {
        field["freeze_target"].removeprefix("run_spec.").split(".", 1)[0]
        for field in backtest_setting_registry.get(application_name).manifest()["run_fields"]
        if field["freeze_target"].startswith("run_spec.")
    }


def test_ic_runspec_contains_exactly_its_registered_run_controls(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace)
    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["ic"],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    run_spec = response.get_json()["run"]["run_spec"]
    controls = {"retention_mode", "step_mode", "output_requests"}
    assert {key for key in run_spec if key in controls} == _run_control_keys("ic_test")
    assert "step_mode" not in run_spec


def test_backtest_runspec_contains_exactly_its_registered_run_controls(client) -> None:
    workspace = _create_workspace(client)
    _update(client, workspace)
    response = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": workspace["configuration"]["revision"],
        "analyses": ["backtest"],
    })

    assert response.status_code == 202, response.get_data(as_text=True)
    run_spec = response.get_json()["run"]["run_spec"]
    controls = {"retention_mode", "step_mode", "output_requests"}
    assert {key for key in run_spec if key in controls} == _run_control_keys("group_test")
    assert run_spec["step_mode"] is False
    assert run_spec["run_spec_version"] == 4
    assert "factor_families" not in run_spec["configuration"]["shared"]
    group = run_spec["configuration"]["analyses"]["backtest"]["groups"][0]
    assert group["factor_candidate_refs"] == [
        workspace["configuration"]["payload"]["shared"]["factors"][0]["ref"],
    ]
    assert {"factorAlias", "factorAliases", "factor_alias", "factor_aliases"}.isdisjoint(group)
    execution_settings = run_spec["configuration"]["analyses"]["backtest"]["execution"]["settings"]
    assert execution_settings["account_currency"] == "USD"
    assert execution_settings["base_currency"] == "CNY"
