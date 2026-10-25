from server.jobs.dispatch.audit import append_audit, list_audit


def test_dispatch_audit_append(tmp_path):
    db = tmp_path / "jobs.db"
    append_audit(db, action="requeue", actor="alice", job_id="job-1", attempt=1)
    rows = list_audit(db)
    assert rows[0]["action"] == "requeue"
    assert rows[0]["actor"] == "alice"
