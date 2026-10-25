from __future__ import annotations

from server.jobs.planning.daemon import PlanningDaemon
from server.jobs.repository.sqlite import JobRepository


def test_planning_daemon_health_and_no_legacy_continue(tmp_path):
    daemon = PlanningDaemon(
        repository=JobRepository(tmp_path / "jobs.db"),
        deployment_id="local", publisher=None,
    )
    assert daemon.health_snapshot()["ok"] is True
    assert daemon.health_snapshot()["celery_planning"] is False
    assert daemon.continue_step("job", {"action": "continue"}) is False
    daemon.set_draining(True)
    assert daemon.health_snapshot()["draining"] is True
