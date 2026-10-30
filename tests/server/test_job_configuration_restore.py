from copy import deepcopy
from dataclasses import replace

import pytest

from server.identity.keycloak_authorization import VerifiedRequestIdentity
from server.jobs.assurance import canonical_hash
from server.jobs.models import JobRecord
from server.jobs.states import JobStatus
from server.manager.services.test_authoring import TestAuthoringError as AuthoringError
from server.manager.services.test_authoring import TestAuthoringService as AuthoringService
from server.services import execution_plans, research_configurations, research_workspaces
from server.services.research_run_identity import hash_run_spec


@pytest.fixture
def frozen_job():
    config = research_configurations.empty_payload()
    config["analyses"]["ic"] = {"custom": {"preserved": 42}}
    run_spec = {"configuration": config, "run_spec_version": 4}
    spec = {
        "run_spec": run_spec,
        "execution_selection": {
            "mode": "manual", "manager_id": "manager-a", "bundles": [],
            "target": {"node_id": "node-a"},
        },
        "retention_mode": "full",
        "task_name": "historical IC",
    }
    return JobRecord(
        job_id="job-a", run_id="run-a", owner="alice", workspace_id="old",
        kind="ic", status=JobStatus.SUCCEEDED,
        owner_issuer="issuer-a", owner_subject="subject-a", job_spec=spec,
        job_spec_hash=canonical_hash(spec), run_spec_hash=hash_run_spec(run_spec),
    )


@pytest.fixture
def restore_environment(monkeypatch, tmp_path, frozen_job):
    import settings
    from server.identity import keycloak_authorization
    from server.jobs import repository

    monkeypatch.setattr(settings, "CACHE_DB_PATH", str(tmp_path / "test.sqlite"))
    identity = VerifiedRequestIdentity("token", "issuer-a", "subject-a", "alice")
    monkeypatch.setattr(keycloak_authorization, "keycloak_request_identity", lambda: identity)
    current = {"job": frozen_job}

    class Repository:
        def load(self, job_id, *, owner):
            job = current["job"]
            return job if job_id == job.job_id and owner == job.owner else None

    monkeypatch.setattr(repository, "JobRepository", Repository)
    return current


def test_restore_creates_new_workspace_from_frozen_job(restore_environment, frozen_job):
    service = AuthoringService()
    path = "/api/test-authoring/jobs/job-a/restore"
    assert service.handles(path, "POST")
    assert not service.handles(path, "GET")
    original = deepcopy(frozen_job.job_spec)
    result = service.write("POST", path, owner="alice", payload={})
    assert result.status == 201
    assert result.payload["source_run_spec_hash"] == frozen_job.run_spec_hash
    assert result.payload["execution_selection_restored"] is True
    workspace = result.payload["workspace"]
    assert workspace["workspace_id"] != frozen_job.workspace_id
    document = execution_plans.document(workspace["configuration"]["payload"])
    assert document["run_spec"]["analyses"] == ["ic"]
    assert document["run_spec"]["configuration"] == original["run_spec"]["configuration"]
    assert document["execution"] == original["execution_selection"]
    assert frozen_job.job_spec == original


def test_legacy_job_restores_configuration_but_requires_new_execution_resolution(restore_environment, frozen_job):
    spec = deepcopy(frozen_job.job_spec)
    spec.pop("execution_selection")
    restore_environment["job"] = replace(frozen_job, job_spec=spec, job_spec_hash=canonical_hash(spec))
    result = AuthoringService().write("POST", "/api/test-authoring/jobs/job-a/restore", owner="alice", payload={})
    assert result.payload["execution_selection_restored"] is False
    plan = execution_plans.document(result.payload["workspace"]["configuration"]["payload"])
    assert plan["run_spec"]["configuration"] == spec["run_spec"]["configuration"]
    assert plan["execution"] == {"mode": "auto", "manager_id": "", "bundles": []}


@pytest.mark.parametrize("mutation", ["owner", "missing_owner", "job_hash", "run_hash", "invalid_selection", "schema", "lossy_normalization"])
def test_restore_refuses_unverified_or_incompatible_records_without_creating_a_workspace(
    restore_environment, frozen_job, mutation,
):
    job = frozen_job
    if mutation == "owner":
        job = replace(job, owner_subject="another-subject")
    elif mutation == "missing_owner":
        job = replace(job, owner_subject="")
    elif mutation == "job_hash":
        job = replace(job, job_spec_hash="not-the-hash")
    elif mutation == "run_hash":
        job = replace(job, run_spec_hash="not-the-hash")
    else:
        spec = deepcopy(job.job_spec)
        if mutation == "invalid_selection":
            spec["execution_selection"] = "invalid"
        elif mutation == "schema":
            spec["run_spec"]["configuration"]["schema_version"] = 0
        else:
            spec["run_spec"]["configuration"]["shared"]["factor_families"] = [{"alias": "old"}]
        job = replace(job, job_spec=spec, job_spec_hash=canonical_hash(spec),
                      run_spec_hash=hash_run_spec(spec["run_spec"]))
    restore_environment["job"] = job
    with pytest.raises((AuthoringError, PermissionError)) as error:
        AuthoringService().write("POST", "/api/test-authoring/jobs/job-a/restore", owner="alice", payload={})
    if mutation != "owner":
        assert error.value.status == 409
    assert research_workspaces.list_workspaces(owner="alice") == []


def test_restore_does_not_disclose_another_users_job(restore_environment):
    with pytest.raises(AuthoringError) as error:
        AuthoringService().write("POST", "/api/test-authoring/jobs/job-a/restore", owner="bob", payload={})
    assert error.value.status == 404
