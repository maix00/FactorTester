from click.testing import CliRunner
from scripts.release import assets
from tools.cli.app import cli


def test_frozen_smoke_commands_exist_in_current_cli(tmp_path, monkeypatch):
    binary = tmp_path / "factortester"
    binary.write_bytes(next(iter(assets._MACHO_PREFIXES)))
    checked = []

    def run_help(binary, *, arguments=None, env=None):
        if env is not None:  # Other entrypoints retain their own frozen smoke checks.
            return
        args = arguments or ["--help"]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        checked.append(args)

    monkeypatch.setattr(assets, "_run_frozen_help", run_help)
    assets._smoke_test_frozen_runtime(binary)
    assert len(checked) == 7
