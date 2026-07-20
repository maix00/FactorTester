from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_agent_contract_is_private_bounded_and_reviewable() -> None:
    scoped = (ROOT / "server" / "AGENTS.md").read_text(encoding="utf-8")
    guide = (
        ROOT / "docs" / "agents" / "server-maintenance.md"
    ).read_text(encoding="utf-8")
    text = scoped + guide
    normalized = " ".join(text.split())

    for required in (
        "server_backend_code",
        "Backend Assurance Gate",
        "Maintenance Case",
        "compact",
        "diagnose",
        "cli-anything",
        "skill-creator",
        "approval",
        "backup",
        "rollback",
        "independent",
        "database statements",
        "token",
    ):
        assert required in text
    assert "continue research without a verifier or LLM review" in normalized
    assert "must never contain server source" in normalized
