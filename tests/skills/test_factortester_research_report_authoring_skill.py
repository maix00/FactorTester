from pathlib import Path


SKILL = (
    Path(__file__).resolve().parents[2]
    / "skills/factortester-research-skill/SKILL.md"
)


def test_research_skill_uses_independent_cli_and_frozen_evidence() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "factortester research reports --help" in text
    assert "factortester research evidence --help" in text
    assert "report workspace ID and branch ID" in text
    assert "RunSpec" in text
    assert "artifact hashes" in text
