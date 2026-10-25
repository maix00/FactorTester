from __future__ import annotations

from server.jobs.dispatch import DispatchMessage, DispatchOutbox
from server.jobs.dispatch import cli


def _message():
    return DispatchMessage("job-cli", 1, "local-docker", "a" * 64, "b" * 64, 8001)


def test_cli_status_show_and_retry(tmp_path, monkeypatch, capsys):
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("FACTORTESTER_JOB_DB", str(db))
    outbox = DispatchOutbox(db, max_attempts=1)
    outbox.enqueue(_message(), now=100.0)
    claimed = outbox.claim(limit=1, now=100.0)[0]
    outbox.mark_failed(claimed.identity, "broker", now=101.0)

    assert cli.main(["status"]) == 0
    assert '"dead"' in capsys.readouterr().out
    assert cli.main(["show", "job-cli", "1"]) == 0
    assert '"service_port": 8001' in capsys.readouterr().out
    assert cli.main(["retry", "job-cli", "1"]) == 0
    assert outbox.get(("job-cli", 1)).status == "pending"
