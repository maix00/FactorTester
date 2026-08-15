from click.testing import CliRunner

from tools.cli.manager_app import manager_cli


def test_legacy_admin_server_surface_is_not_exposed() -> None:
    result = CliRunner().invoke(manager_cli, ["admin", "--help"])

    assert result.exit_code != 0
    assert "No such command" in result.output
