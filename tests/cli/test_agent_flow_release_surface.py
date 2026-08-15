from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.manager_app import manager_cli


def test_public_cli_does_not_offer_backend_maintenance_authority() -> None:
    runner = CliRunner()

    resume = runner.invoke(cli, ["agent-flow", "resume", "--help"])
    research_reserve = runner.invoke(
        cli,
        ["agent-flow", "invocation", "reserve", "--help"],
    )
    reserve = runner.invoke(
        manager_cli,
        ["agent-flow", "invocation", "reserve", "--help"],
    )

    assert resume.exit_code == 0
    assert research_reserve.exit_code != 0
    assert reserve.exit_code == 0
    combined = resume.output + reserve.output
    assert "server_maintenance" not in combined
    assert "server_backend_code" not in combined
    assert "implementation_agent" not in combined
    assert "backend_verifier" not in combined


def test_research_and_manager_command_surfaces_are_separate() -> None:
    runner = CliRunner()
    research_help = runner.invoke(cli, ["--help"])
    manager_help = runner.invoke(manager_cli, ["--help"])
    research_client_help = runner.invoke(cli, ["client", "--help"])
    manager_client_help = runner.invoke(
        manager_cli, ["client", "--help"],
    )

    assert research_help.exit_code == 0
    assert manager_help.exit_code == 0
    assert research_client_help.exit_code == 0
    assert manager_client_help.exit_code == 0
    assert "admin" not in research_help.output
    assert "restart-fleet" not in research_help.output
    assert not any(
        line.lstrip().startswith("release ")
        for line in research_client_help.output.splitlines()
    )
    assert "admin" in manager_help.output
    assert "restart-fleet" in manager_help.output
    assert any(
        line.lstrip().startswith("release ")
        for line in manager_client_help.output.splitlines()
    )
