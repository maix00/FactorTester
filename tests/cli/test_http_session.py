from __future__ import annotations

import json
from pathlib import Path

from tools.cli.agent_auth import AgentCapability
from tools.cli.http import HttpSession


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._raw


def test_successful_response_survives_cookie_persistence_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = HttpSession(
        "http://127.0.0.1:7998",
        cookies=tmp_path / "cookies.lwp",
    )
    monkeypatch.setattr(
        session._opener,
        "open",
        lambda *_args, **_kwargs: _Response({"success": True, "items": [1]}),
    )
    monkeypatch.setattr(
        session.cookie_jar,
        "save",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError("read-only")),
    )

    assert session.get("/api/products") == {"success": True, "items": [1]}


def test_profile_capability_does_not_persist_manager_cookies(tmp_path: Path) -> None:
    capability = AgentCapability(
        base_url="http://127.0.0.1:7998",
        token="short-lived-token",
        profile_id="profile-main",
        claim_id="claim-main",
    )

    session = HttpSession(
        capability.base_url,
        cookies=tmp_path / "cookies.lwp",
        agent_capability=capability,
    )

    assert session.persist_cookies is False
    assert not hasattr(session.cookie_jar, "filename")


def test_publication_uses_profile_session_and_preserves_idempotency(tmp_path, monkeypatch):
    import pytest
    from tools.cli.http import HttpClientError
    from tools.cli.release.research_reporting.public_research.client import (
        PublicResearchClient, ManagerRequestError,
    )
    capability = AgentCapability(base_url="http://127.0.0.1:7998", token="test-capability",
                                 profile_id="self", claim_id="test-claim")
    session = HttpSession(capability.base_url, cookies=tmp_path / "unused",
                          agent_capability=capability, bearer_token=capability.token)
    seen = []
    def opened(request, **kwargs):
        seen.append(request)
        return _Response({"success": True})
    monkeypatch.setattr(session._opener, "open", opened)
    client = PublicResearchClient(tmp_path, session=session)
    assert client.credentials is None
    client._request("POST", "/api/transfers/objects/access", payload={"object_id": "asset"},
                    extra_headers={"Idempotency-Key": "upload-1"})
    headers = {key.lower(): value for key, value in seen[0].header_items()}
    assert headers["authorization"] == "Bearer test-capability"
    assert headers["x-factortester-agent-profile"] == "self"
    assert headers["x-factortester-agent-claim"] == "test-claim"
    assert headers["idempotency-key"] == "upload-1"
    with pytest.raises(ValueError, match="match the authenticated"):
        PublicResearchClient(tmp_path, session=session, manager_url="http://other:7998")
    with pytest.raises(ValueError, match="Only Idempotency-Key"):
        session.request("POST", "/api/test", extra_headers={"authorization": "other"})
    def conflict(*args, **kwargs):
        raise HttpClientError(409, "http://127.0.0.1:7998/api/test", "version conflict")
    monkeypatch.setattr(session, "request", conflict)
    with pytest.raises(ManagerRequestError) as error:
        client._request("POST", "/api/test")
    assert error.value.status_code == 409
    assert not error.value.retryable


def test_current_principal_uses_manager_session_contract(tmp_path, monkeypatch):
    from tools.cli.client import FactorTesterClient

    session = HttpSession("http://127.0.0.1:7998", cookies=tmp_path / "cookies")
    seen = []
    def opened(request, **kwargs):
        seen.append(request.full_url)
        return _Response({"success": True, "username": "test-principal", "role": "user"})
    monkeypatch.setattr(session._opener, "open", opened)
    assert FactorTesterClient(session).current_principal()["username"] == "test-principal"
    assert seen == ["http://127.0.0.1:7998/api/session"]
