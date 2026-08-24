from __future__ import annotations

from pathlib import Path

from flask import Flask

from server.modules.custom_factors import (
    cf_bp,
    crud_routes,
    factor_library_service,
)

ROOT = Path(__file__).parents[2]


def _app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.secret_key = "factor-library-mutations-test"
    app.register_blueprint(cf_bp)
    return app


def _login(client, username: str = "alice") -> None:
    with client.session_transaction() as session:
        session["username"] = username


def test_public_family_mutations_are_superadmin_only(monkeypatch) -> None:
    client = _app().test_client()
    _login(client)

    def deny() -> bool:
        return False

    monkeypatch.setattr(crud_routes, "_current_user_is_super_admin", deny)
    denied = client.post(
        "/custom-factors/api/create-public",
        json={"source_code": "class PublicAlpha(FactorFamily):\n    pass"},
    )
    assert denied.status_code == 403

    stored: list[tuple[str, str]] = []
    invalidated: list[str] = []
    def allow() -> bool:
        return True

    def no_public_factors() -> list:
        return []

    monkeypatch.setattr(crud_routes, "_current_user_is_super_admin", allow)
    monkeypatch.setattr(crud_routes, "list_public_factors", no_public_factors)
    monkeypatch.setattr(
        crud_routes,
        "save_public_factor_source",
        lambda factor_id, source: stored.append((factor_id, source)),
    )
    monkeypatch.setattr(
        crud_routes, "invalidate_factor_family_cache", invalidated.append,
    )
    created = client.post(
        "/custom-factors/api/create-public",
        json={
            "source_code": "class PublicAlpha(FactorFamily):\n    pass",
            "chinese_name": "公共动量",
        },
    )
    assert created.status_code == 200
    assert created.get_json()["factor"]["id"] == "PublicAlpha"
    assert stored and stored[0][0] == "PublicAlpha"

    monkeypatch.setattr(
        crud_routes, "load_public_factor_source", lambda _factor_id: stored[0][1],
    )
    deleted: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        crud_routes,
        "delete_factor_source_row",
        lambda kind, owner, factor_id: deleted.append((kind, owner, factor_id)),
    )
    removed = client.post("/custom-factors/api/delete-public/PublicAlpha")
    assert removed.status_code == 200
    assert deleted == [("public", "", "PublicAlpha")]
    assert invalidated == ["PublicAlpha", "PublicAlpha"]


def test_deleting_one_registered_factor_preserves_other_rows(monkeypatch) -> None:
    class Family:
        def get_alias(self, **row):
            return f"Family|N:{row['N']}"

    monkeypatch.setattr(
        factor_library_service,
        "load_factor_param_config",
        lambda *_args, **_kwargs: {
            "params_list": [{"N": "1d"}, {"N": "5d"}],
            "metadata": {"note": "keep"},
        },
    )
    monkeypatch.setattr(
        factor_library_service,
        "get_factor_family_instance",
        lambda *_args, **_kwargs: Family(),
    )
    saved = []
    monkeypatch.setattr(
        factor_library_service,
        "save_factor_param_config",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )
    assert factor_library_service.delete_factor_library_factor(
        "alice", "Family", "Family|N:1d", "CNFutures",
    ) is True
    assert saved[0][0][0:4] == (
        "alice", "Family", [{"N": "5d"}], "CNFutures",
    )
    assert saved[0][1]["metadata"] == {"note": "keep"}
