from __future__ import annotations

from pathlib import Path

from flask import Flask

from server.modules.custom_factors import (
    crud_routes,
    factor_library_internal_bp,
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
    app.register_blueprint(factor_library_internal_bp)
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
        "/api/internal/factor-library/families/public",
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
        lambda factor_id, source, **_metadata: stored.append((factor_id, source)),
    )
    monkeypatch.setattr(
        crud_routes, "invalidate_factor_family_cache", invalidated.append,
    )
    monkeypatch.setattr(
        crud_routes,
        "_family_formula_fingerprint",
        lambda *_args: "a" * 64,
    )
    monkeypatch.setattr(
        crud_routes,
        "record_factor_formula_version",
        lambda *_args, **_kwargs: {},
    )
    created = client.post(
        "/api/internal/factor-library/families/public",
        json={
            "source_code": "class PublicAlpha(FactorFamily):\n    pass",
            "chinese_name": "公共动量",
        },
    )
    assert created.status_code == 200
    assert created.get_json()["factor"]["id"] == "PublicAlpha"
    assert created.get_json()["factor"]["family_formula_fingerprint"] == "a" * 64
    assert "git_commit_sha" not in created.get_json()["factor"]
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
    removed = client.delete(
        "/api/internal/factor-library/families/public/PublicAlpha"
    )
    assert removed.status_code == 200
    assert deleted == [("public", "", "PublicAlpha")]
    assert invalidated == ["PublicAlpha", "PublicAlpha"]


def test_public_family_save_succeeds_without_server_git_workspace(monkeypatch) -> None:
    client = _app().test_client()
    _login(client, "root")

    monkeypatch.setattr(crud_routes, "_current_user_is_super_admin", lambda: True)
    monkeypatch.setattr(crud_routes, "list_public_factors", lambda: [])
    monkeypatch.setattr(
        crud_routes, "save_public_factor_source", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(crud_routes, "invalidate_factor_family_cache", lambda *_args: None)
    monkeypatch.setattr(
        crud_routes,
        "_family_formula_fingerprint",
        lambda *_args: "b" * 64,
    )
    snapshots = []
    monkeypatch.setattr(
        crud_routes,
        "record_factor_formula_version",
        lambda *args, **kwargs: snapshots.append((args, kwargs)) or {
            "family_formula_fingerprint": kwargs["family_formula_fingerprint"],
            "source_sha256": "hash",
        },
    )

    response = client.post(
        "/api/internal/factor-library/families/public",
        json={"source_code": "class PublicAlpha(FactorFamily):\n    pass"},
    )

    assert response.status_code == 200
    assert "git_commit_sha" not in response.get_json()["factor"]
    assert snapshots
    assert snapshots[0][1]["family_formula_fingerprint"] == "b" * 64


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
