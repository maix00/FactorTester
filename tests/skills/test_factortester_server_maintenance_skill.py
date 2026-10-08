from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "server" / "skills" / "factortester-server-maintenance"


def test_server_maintenance_skill_routes_all_supported_case_types() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "name: factortester-server-maintenance" in skill
    assert "容器、网络与发布" in skill
    for reference in (
        "backend-change.md",
        "database-change.md",
        "infrastructure.md",
    ):
        assert f"references/{reference}" in skill
        assert (SKILL_ROOT / "references" / reference).is_file()


def test_infrastructure_reference_is_progressively_disclosed_and_cli_first() -> None:
    reference = (SKILL_ROOT / "references" / "infrastructure.md").read_text(
        encoding="utf-8"
    )

    # Verify semantic boundaries, not English wording or document length.
    assert "## 入口与目标" in reference
    for required in (
        "现成部署脚本",
        "management_access",
        "控制面",
        "数据面",
        "PostgreSQL",
        "docker system prune",
        "--json",
        "cli-anything-factortester-server",
        "node_unreachable",
    ):
        assert required in reference


def test_server_maintenance_ui_metadata_matches_skill_contract() -> None:
    metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert 'display_name: "FactorTester 服务器维护"' in metadata
    assert (
        'short_description: "审计并维护已授权的 FactorTester 服务器、容器与网络部署"'
        in metadata
    )
    assert 'default_prompt: |\n' in metadata
    assert '使用 $factortester-server-maintenance' in metadata


def test_research_skill_points_to_independent_research_cli() -> None:
    research = (
        ROOT / "skills" / "factortester-research-skill" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "factortester research --help" in research
