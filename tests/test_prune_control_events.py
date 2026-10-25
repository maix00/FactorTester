import sqlite3
import time

from scripts.server.prune_control_events import main


def _database(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE control_events (event_id TEXT PRIMARY KEY, created_at REAL, sequence INTEGER, payload TEXT)")
    connection.execute("CREATE TABLE control_sync_cursors (source_server_id TEXT, sequence INTEGER)")
    connection.execute("INSERT INTO control_events VALUES ('old', ?, 1, 'x')", (time.time() - 40 * 86400,))
    connection.execute("INSERT INTO control_events VALUES ('new', ?, 2, 'x')", (time.time(),))
    connection.commit()
    connection.close()


def test_dry_run_keeps_events(tmp_path, capsys):
    path = tmp_path / "index.sqlite"
    _database(path)
    assert main_path(path, []) == 0
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM control_events").fetchone()[0] == 2


def test_apply_deletes_only_old_events(tmp_path):
    path = tmp_path / "index.sqlite"
    _database(path)
    assert main_path(path, ["--apply"]) == 0
    connection = sqlite3.connect(path)
    assert [row[0] for row in connection.execute("SELECT event_id FROM control_events")] == ["new"]


def main_path(path, extra):
    import sys
    argv = ["prune_control_events.py", str(path), *extra]
    old = sys.argv
    sys.argv = argv
    try:
        return main()
    finally:
        sys.argv = old
