from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.domain.federation import ServiceRoute
from server.manager.http.gateway import GatewayResponse


@contextmanager
def running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def authenticated_state(tmp_path):
    state = manager.ManagerState(
        tmp_path,
        "python",
        session_db_path=tmp_path / "manager-sessions.sqlite",
    )
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    return state


def agent_headers(state, *, profile_id="profile-main", claim_id="claim-1"):
    issued = state.issue_agent_session("user@1", profile_id, claim_id)
    return {
        "Authorization": f"Bearer {issued['token']}",
        "X-FactorTester-Agent": "profile",
        "X-FactorTester-Agent-Profile": profile_id,
        "X-FactorTester-Agent-Claim": claim_id,
    }


def test_local_profile_agent_unknown_get_does_not_fall_back_to_service_gateway(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state, "route_request",
        lambda *_args, **_values: pytest.fail(
            "unknown Agent GET must not reach a business service"
        ),
    )
    headers = agent_headers(state)
    paths = (
        "/custom-factors/api/list",
        "/custom-factors/api/factor-library-overview",
        "/api/future-cli-capability?detail=1",
    )
    with running_manager(state) as base_url:
        for path in paths:
            with pytest.raises(HTTPError) as failed:
                urlopen(Request(f"{base_url}{path}", headers=headers))
            assert failed.value.code == 404


def test_profile_agent_uses_canonical_factor_library_gateway(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    route = ServiceRoute(
        server_id=state.server_id,
        role="main",
        branch="main",
        revision="test",
        port=8000,
    )
    monkeypatch.setattr(state, "route_for", lambda **_values: route)
    forwarded = []

    def route_request(selected, **values):
        forwarded.append((selected, values))
        return GatewayResponse(
            status=200,
            body=json.dumps({"success": True, "items": []}).encode(),
            content_type="application/json",
        )

    monkeypatch.setattr(state, "route_request", route_request)
    with running_manager(state) as base_url:
        for path in (
            "/api/factor-library/catalog",
            "/api/factor-library/operators",
            "/api/factor-library/research-runs?limit=1",
            "/api/admin/server-instances",
        ):
            with urlopen(Request(
                f"{base_url}{path}", headers=agent_headers(state),
            )) as response:
                assert json.loads(response.read())["success"] is True

    assert {values["principal"] for _route, values in forwarded} == {"user@1"}
    assert [values["path"] for _route, values in forwarded] == [
        "/custom-factors/api/list",
        "/custom-factors/api/visual-operators",
        "/custom-factors/api/factor-library-research-runs?limit=1",
        "/admin/api/server-instances",
    ]


def test_local_profile_agent_unknown_write_does_not_fall_back_to_service_gateway(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state, "route_request",
        lambda *_args, **_values: pytest.fail(
            "unknown Agent write must not reach a business service"
        ),
    )
    body = b'{"enabled":true}'
    headers = {**agent_headers(state), "Content-Type": "application/json"}
    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as failed:
            urlopen(Request(
                f"{base_url}/api/future-cli-capability",
                data=body,
                headers=headers,
                method="POST",
            ))
        assert failed.value.code == 404


def test_local_profile_agent_cannot_target_a_remote_service(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state,
        "route_for",
        lambda **_values: pytest.fail("remote Agent target must be rejected"),
    )
    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as failed:
            urlopen(Request(
                f"{base_url}/api/factor-library/catalog"
                "?server_id=remote-main",
                headers=agent_headers(state),
            ))

    assert failed.value.code == 403
    payload = json.loads(failed.value.read())
    assert payload["code"] == "agent_service_target_must_be_local"


def test_invalid_profile_agent_cannot_use_service_gateway_fallback(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state,
        "route_request",
        lambda *_args, **_values: pytest.fail("invalid Agent must not be proxied"),
    )
    headers = {
        **agent_headers(state),
        "X-FactorTester-Agent-Claim": "wrong-claim",
    }
    with running_manager(state) as base_url:
        with pytest.raises(HTTPError) as failed:
            urlopen(Request(
                f"{base_url}/api/future-cli-capability", headers=headers,
            ))

    assert failed.value.code == 404


def test_manager_owned_routes_precede_profile_agent_service_fallback(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state,
        "route_request",
        lambda *_args, **_values: pytest.fail("Manager route must stay local"),
    )
    with running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/client/preferences",
            headers=agent_headers(state),
        )) as response:
            value = json.loads(response.read())

    assert value["preferences"]["language"] == "system"


def test_profile_agent_research_catalog_precedes_service_fallback(
    tmp_path, monkeypatch,
) -> None:
    state = authenticated_state(tmp_path)
    monkeypatch.setattr(
        state,
        "route_request",
        lambda *_args, **_values: pytest.fail(
            "Manager research routes must stay local"
        ),
    )
    headers = agent_headers(state)
    paths = (
        "/api/public-research?scope=shared",
        "/api/research-publications/settings",
    )
    with running_manager(state) as base_url:
        for path in paths:
            with urlopen(Request(f"{base_url}{path}", headers=headers)) as response:
                value = json.loads(response.read())
                status = response.status

            assert status == 200
            assert value["reports"] == []
