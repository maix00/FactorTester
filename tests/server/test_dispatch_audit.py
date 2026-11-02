from server.jobs.dispatch.audit import append_audit, list_audit
from concurrent.futures import ThreadPoolExecutor
import pytest


def test_dispatch_audit_append(tmp_path):
    db = tmp_path / "jobs.db"
    append_audit(db, action="requeue", actor="alice", job_id="job-1", attempt=1)
    rows = list_audit(db)
    assert rows[0]["action"] == "requeue"
    assert rows[0]["actor"] == "alice"


def test_idempotent_audit_serializes_retries_and_rejects_changed_detail(tmp_path):
    db = tmp_path / "jobs.db"
    def append(_):
        append_audit(db, action="manager-organization-bind-intent", actor="alice",
                     job_id="operation-1", detail="same", idempotent=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(8)))
    assert len(list_audit(db)) == 1
    with pytest.raises(ValueError, match="different details"):
        append_audit(db, action="manager-organization-bind-intent", actor="alice",
                     job_id="operation-1", detail="different", idempotent=True)
