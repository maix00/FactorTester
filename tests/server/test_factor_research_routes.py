from __future__ import annotations

from flask import Flask
from hashlib import sha256
import json

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors import factor_library_routes as routes


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(cf_bp)
    return app


def _login(client, username: str = "alice") -> None:
    with client.session_transaction() as session:
        session["username"] = username


def test_factor_research_save_route_passes_structured_metadata(monkeypatch):
    captured: dict = {}

    def save_run(username: str, **kwargs):
        captured["username"] = username
        captured.update(kwargs)
        return {"run_id": "run-1", **kwargs}

    monkeypatch.setattr(routes, "save_factor_research_run", save_run)
    client = _app().test_client()
    _login(client)

    response = client.post(
        "/custom-factors/api/factor-library-research-runs",
        json={
            "ff_alias": "SgCCS",
            "factor_alias": "SgCCS|N:2m",
            "product_group": "core8",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "test_type": "ic",
            "config": {"research_meta": {"sample_role": "oos"}},
            "metrics": {"ic_mean": 0.02},
            "sample_role": "oos",
            "regime_label": "shock",
            "slice_name": "jan",
        },
    )

    assert response.status_code == 200
    assert captured["username"] == "alice"
    assert captured["sample_role"] == "oos"
    assert captured["regime_label"] == "shock"
    assert captured["slice_name"] == "jan"
    assert captured["metrics"] == {"ic_mean": 0.02}


def test_factor_research_list_route_aggregates_visible_users(monkeypatch):
    monkeypatch.setattr(routes, "visible_usernames_for", lambda username: ["alice", "bob"])

    def list_runs(username: str, **kwargs):
        return [
            {
                "run_id": f"{username}-run",
                "factor_alias": "F|N:1",
                "test_type": "ic",
                "product_group": "core",
                "updated_at": 1 if username == "alice" else 2,
                "metrics": {"ic_mean": 0.01 if username == "alice" else 0.03},
            }
        ]

    monkeypatch.setattr(routes, "list_factor_research_runs", list_runs)
    client = _app().test_client()
    _login(client)

    response = client.get(
        "/custom-factors/api/factor-library-research-runs"
        "?include_subordinates=1&metric=ic_mean&limit=2"
    )

    payload = response.get_json()
    assert payload["success"] is True
    assert [run["run_id"] for run in payload["runs"]] == ["bob-run", "alice-run"]


def test_factor_research_stability_route_uses_preset_and_thresholds(monkeypatch):
    monkeypatch.setattr(routes, "visible_usernames_for", lambda username: [username])
    monkeypatch.setattr(
        routes,
        "list_factor_research_runs",
        lambda username, **kwargs: [
            {
                "run_id": "r1",
                "factor_alias": "F|N:1",
                "test_type": "ic",
                "product_group": "core",
                "start_date": "2026-01-01",
                "metrics": {"ic_mean": 0.03, "ic_t_stat": 2.4},
            },
            {
                "run_id": "r2",
                "factor_alias": "F|N:1",
                "test_type": "ic",
                "product_group": "core",
                "start_date": "2026-04-01",
                "metrics": {"ic_mean": -0.01, "ic_t_stat": -0.5},
            },
        ],
    )
    client = _app().test_client()
    _login(client)

    response = client.get(
        "/custom-factors/api/factor-library-research-stability"
        "?preset=ic-stable&by=quarter"
    )

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["preset"]["metric"] == "ic_mean"
    assert payload["rows"][0]["periods"] == 2
    assert payload["rows"][0]["pass_count"] == 1


def test_client_factor_library_projection_is_bounded_and_source_free(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        routes,
        "can_view_user_scope",
        lambda current, owner: current == owner == "18717974771",
    )
    monkeypatch.setattr(
        routes,
        "build_factor_library_overview",
        lambda username, include_subordinates, product_group=None: {
            "factors": [{
                "factor_alias": "SgCCS",
                "owner_username": "18717974771",
                "product_group": "CNFutures",
                "source_code": "must not cross the boundary",
                "math_expr": "must not cross the boundary",
            }],
        },
    )
    client = _app().test_client()
    _login(client, "18717974771")

    response = client.get(
        "/custom-factors/api/client/factor-library-sources/"
        "18717974771/projection"
    )

    assert response.status_code == 200
    payload = response.get_json()
    projection = payload["projection"]
    assert projection["principal"] == projection["owner_ref"] == "18717974771"
    assert projection["factors"] == [{
        "factor_alias": "SgCCS",
        "owner_username": "18717974771",
        "product_group": "CNFutures",
    }]
    assert "source_code" not in json.dumps(projection)
    assert "math_expr" not in json.dumps(projection)
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert payload["projection_hash"] == sha256(encoded).hexdigest()


def test_client_factor_library_projection_rejects_invisible_owner(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        routes,
        "can_view_user_scope",
        lambda current, owner: False,
    )
    client = _app().test_client()
    _login(client, "18717974771")

    response = client.get(
        "/custom-factors/api/client/factor-library-sources/other/projection"
    )

    assert response.status_code == 403
