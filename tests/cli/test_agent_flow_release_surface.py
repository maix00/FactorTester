from click.testing import CliRunner

from tools.cli.app import cli


def test_public_cli_does_not_offer_backend_maintenance_authority() -> None:
    runner = CliRunner()

    resume = runner.invoke(cli, ["agent-flow", "resume", "--help"])
    reserve = runner.invoke(
        cli,
        ["agent-flow", "invocation", "reserve", "--help"],
    )

    assert resume.exit_code == 0
    assert reserve.exit_code == 0
    combined = resume.output + reserve.output
    assert "server_maintenance" not in combined
    assert "server_backend_code" not in combined
    assert "implementation_agent" not in combined
    assert "backend_verifier" not in combined
