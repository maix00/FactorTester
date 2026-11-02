from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http import job_list_routes as module
from server.manager.http.job_list_routes import JobListRoutesMixin


def test_revoked_admin_token_never_reads_private_server_or_cross_server_jobs(monkeypatch):
    responses, calls = [], []
    monkeypatch.setattr(module, "json_response", lambda _handler, value, status=200: responses.append((status, value)))
    monkeypatch.setattr(module, "current_manager_role", lambda *_: False)
    class Handler(JobListRoutesMixin):
        state = SimpleNamespace(
            aggregate_public_jobs=lambda **_: calls.append("public") or {"jobs": [], "public": True},
            aggregate_server_jobs=lambda **_: pytest.fail("revoked admin read private jobs"),
            aggregate_cross_server_jobs=lambda **_: pytest.fail("revoked admin read peer jobs"),
        )
        def _session(self):
            return {"username": "alice", "role": "super_admin", "keycloak_roles": ["admin_console:manage"]}
        def _visitor_mode(self): return None
        def _bearer_token(self): return "old-token"
        def _proxy_selected_job_list(self, _parsed): return False
        def _proxy_product_data_service(self, _parsed, *, method): return False
    handler = Handler()
    handler._get_job_list_routes(urlparse("/api/jobs?scope=server"))
    assert calls == ["public"] and responses[-1][1]["public"] is True
    handler._get_job_list_routes(urlparse("/api/jobs?scope=cross-server&source_scope=server"))
    assert responses[-1][0] == 403 and calls == ["public"]


def test_subordinate_projection_uses_current_groups_without_stale_directory_cache(monkeypatch):
    from server.identity import keycloak_directory
    observed = []
    monkeypatch.setattr(module, "current_administrative_groups", lambda _: ("/current-admin-group",))
    monkeypatch.setattr(module, "current_manager_role", lambda *_: False)
    monkeypatch.setattr(keycloak_directory, "managed_users_for_claims", lambda **kwargs:
        observed.append(kwargs) or [{"username": "child"}])
    session = {"username": "alice", "keycloak_groups": ["/revoked-group"],
               "keycloak_roles": ["admin_console:manage"]}
    assert JobListRoutesMixin()._subordinate_users(session) == [{"username": "child"}]
    assert observed == [{"groups": ("/current-admin-group",), "roles": (), "use_cache": False}]
