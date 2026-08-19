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
