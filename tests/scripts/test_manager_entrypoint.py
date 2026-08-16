from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "deploy" / "docker" / "factortester-server" / "manager-entrypoint.sh"


def test_hot_reload_restarts_manager_after_child_exit() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")

    assert "watchmedo auto-restart" in source
    assert "--no-restart-on-command-exit" not in source
