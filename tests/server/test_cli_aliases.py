import tomllib
from pathlib import Path


def test_traderesearch_cli_aliases_share_legacy_entrypoints():
    config = tomllib.loads(Path("tools/cli/pyproject.toml").read_text())
    scripts = config["project"]["scripts"]
    assert scripts["traderesearch"] == scripts["factortester"]
    assert scripts["traderesearch-manager"] == scripts["factortester-manager"]
