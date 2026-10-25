from __future__ import annotations

from click.testing import CliRunner

from tools.cli.commands import research


class _Client:
    def get_job(self, job_id):
        return {
            "job_id": job_id,
            "status": "running",
            "attempt": 1,
            "server_context": {"server_id": "remote-main", "port": 8001},
            "progress": {
                "sequence": 2, "phase": "event_replay",
                "completed": 5, "total": 10, "percent": 50.0,
            },
        }


def test_job_queue_json(monkeypatch):
    monkeypatch.setattr(research, "client_from_config", lambda: _Client())
    result = CliRunner().invoke(research.job, ["queue", "job-1", "--json"])
    assert result.exit_code == 0, result.output
    assert '"queue": "factortester.jobs.remote-main.8001"' in result.output
    assert '"percent": 50.0' in result.output


def test_job_queue_text(monkeypatch):
    monkeypatch.setattr(research, "client_from_config", lambda: _Client())
    result = CliRunner().invoke(research.job, ["queue", "job-1"])
    assert result.exit_code == 0, result.output
    assert "factortester.jobs.remote-main.8001" in result.output
    assert "5/10" in result.output
