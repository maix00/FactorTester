from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "skills/cli-anything-factortester-research/SKILL.md"
PACKAGED = (
    ROOT
    / "tools/cli/agent-harness/cli_anything/factortester_research/skills"
    / "SKILL.md"
)


def test_research_agent_skill_requires_explicit_special_section_labels() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "--kind special" in canonical
    assert "--display-kind grill_resolution" in canonical
    assert "--display-kind external_review" in canonical
    assert "the Agent must create" in canonical
    assert "the container itself with `--kind special`" in canonical
    assert "Do not publish that container as an ordinary" in canonical
    assert "must name its actual `--parent-id`" in canonical
