from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "server" / "skills" / "server-maintenance"


def test_server_maintenance_skill_routes_all_supported_case_types() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "name: server-maintenance" in skill
    assert "Docker/WireGuard/SSH deployment" in skill
    for reference in (
        "backend-change.md",
        "database-change.md",
        "graph-governance.md",
        "infrastructure.md",
    ):
        assert f"references/{reference}" in skill
        assert (SKILL_ROOT / "references" / reference).is_file()


def test_infrastructure_reference_is_progressively_disclosed_and_cli_first() -> None:
    reference = (SKILL_ROOT / "references" / "infrastructure.md").read_text(
        encoding="utf-8"
    )

    assert len(reference.splitlines()) > 100
    assert "## Contents" in reference
    for required in (
        "TCP 7998",
        "TCP 7997",
        "TCP 17998",
        "TCP 17997",
        "UDP 51820",
        "UDP 51821",
        "docker system prune",
        "local `2222`",
        "--json",
        "real Docker, Git, SSH",
        "cli-anything-factortester-server",
        "node_unreachable",
    ):
        assert required in reference


def test_server_maintenance_ui_metadata_matches_skill_contract() -> None:
    metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert 'display_name: "Server Maintenance"' in metadata
    assert (
        'short_description: "审计并维护私有 FactorTester 服务器、容器与网络部署"'
        in metadata
    )
    assert 'default_prompt: "Use $server-maintenance ' in metadata


def test_research_skill_points_to_registered_server_maintenance_skill() -> None:
    research = (
        ROOT / "skills" / "cli-anything-factortester-research" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "registered `$server-maintenance` Skill" in research
    assert "references/infrastructure.md" in research
