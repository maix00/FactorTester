from __future__ import annotations

from types import SimpleNamespace

from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus
from server.manager.services.dispatch_overview import dispatch_overview


class _Registry:
    def servers(self, include_offline=True):
        return [
            {"server_id": "local", "role": "feat", "online": True,
             "ports": [{"port": 8000}, {"port": 8001}]},
            {"server_id": "remote", "role": "main", "online": False,
             "ports": [{"port": 8000}]},
        ]


def _state():
    return SimpleNamespace(
        server_id="local",
        server_role="feat",
        worktrees=lambda: [SimpleNamespace(port=8000), SimpleNamespace(port=8001)],
        federation_registry=_Registry(),
    )


def test_dispatch_overview_includes_servers_ports_and_local_outbox(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    repository.heartbeat_worker_target("local", 8001, "worker-a", ttl_seconds=60)
    repository.create(JobRecord(
        job_id="overview-job", run_id="run", owner="alice", workspace_id="ws",
        kind="backtest", status=JobStatus.SUBMITTED, deployment_id="local",
        service_port=8001, run_spec_hash="a" * 64, job_spec={},
    ))
    repository.transition("overview-job", JobStatus.PLANNING)
    repository.transition("overview-job", JobStatus.QUEUED)

    payload = dispatch_overview(_state(), repository)
    assert payload["outbox"]["pending"] == 1
    assert "available" in payload["nautilus"]
    assert isinstance(payload["audit"], list)
    assert payload["local_targets"] == [
        {"port": 8000, "queue": "factortester.jobs.local.8000", "worker_online": False},
        {"port": 8001, "queue": "factortester.jobs.local.8001", "worker_online": True},
    ]
    remote = next(item for item in payload["servers"] if item["server_id"] == "remote")
    assert remote["online"] is False
    assert remote["ports"][0]["queue"] == "factortester.jobs.remote.8000"


def test_dispatch_overview_merges_remote_status(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    def remote(server_id):
        assert server_id == "remote"
        return {
            "outbox": {"pending": 4},
            "workers": [{"service_port": 8000, "online": True}],
        }
    state = _state()
    state.federation_registry.servers = lambda include_offline=True: [
        {"server_id": "local", "role": "feat", "online": True,
         "ports": [{"port": 8000}, {"port": 8001}]},
        {"server_id": "remote", "role": "main", "online": True,
         "ports": [{"port": 8000}]},
    ]
    payload = dispatch_overview(state, repository, remote_status=remote)
    item = next(row for row in payload["servers"] if row["server_id"] == "remote")
    assert item["remote_outbox"] == {"pending": 4}
    assert item["ports"][0]["worker_online"] is True
