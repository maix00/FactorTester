from __future__ import annotations

from pathlib import Path


def test_session_secret_is_stable_and_private(monkeypatch, tmp_path: Path):
    secret_path = tmp_path / "session-secret"
    monkeypatch.setenv("FACTORTESTER_SESSION_SECRET_FILE", str(secret_path))
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    from server.services.session_secret import load_session_secret

    first = load_session_secret()
    second = load_session_secret()

    assert first == second
    assert len(first) == 64
    assert secret_path.read_text(encoding="utf-8") == first
    assert secret_path.stat().st_mode & 0o777 == 0o600


def test_configured_session_secret_wins(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLASK_SECRET_KEY", "configured-secret")
    monkeypatch.setenv(
        "FACTORTESTER_SESSION_SECRET_FILE", str(tmp_path / "unused")
    )

    from server.services.session_secret import load_session_secret

    assert load_session_secret() == "configured-secret"
