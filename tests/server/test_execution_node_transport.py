"""Real HTTP/Job repository; deterministic introspection fixture.

Actual Keycloak + native execution is covered by verify_remote_node_job.
"""
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
import threading
import urllib.error

import pytest

from server.jobs.assurance import canonical_hash
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.dispatch.remote import RemoteJobRepository
from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus
from server.manager.http.peer_handler import PeerControlHandler
from server.manager.storage.transfers.node_identities import NodeIdentityRegistry
from server.identity.service_access import ServiceHTTPClient, ServiceTokenVerifier
from tests.server.test_execution_data_binding import _offer, _requirement, _target


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    repo = JobRepository(tmp_path / "manager.sqlite")
    import time
    class IdentityFixture:
        def client_credentials(self, **kwargs):
            return {"access_token":"fixture-node-token", "expires_in":60}
        def introspect(self, token):
            return {"active":token=="fixture-node-token", "iss":"https://identity.invalid/realms/test",
                    "aud":["manager-a"],"exp":time.time()+60,"sub":"node-service",
                    "tr_node_id":"node-b","scope":"tr:execution:node"}
    identity=IdentityFixture()
    state=SimpleNamespace(session=lambda _token:None,server_id="manager-a",job_repository=repo,
        execution_token_verifier=ServiceTokenVerifier(identity,issuer="https://identity.invalid/realms/test",audience="manager-a"))
    class Handler(PeerControlHandler):
        pass
    Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    client = ServiceHTTPClient(f"http://127.0.0.1:{server.server_port}", oidc=identity)
    descriptor = {"target": asdict(_target()), "service_port": 8000,
                  "offers": [asdict(_offer())], "runtime_adapters": {_offer().source_ref: {
        "member_key": "minute", "adapter_id": "native-v1", "frequency": "MIN1",
        "instrument_scope": "physical_contract", "clock_policy": "bar-end"}}}
    remote = RemoteJobRepository(client, descriptor)
    route = remote.register()
    service = ExecutionNodeService(repo, manager_id="manager-a")
    binding = service.bind(target=descriptor["target"], requirements=[asdict(_requirement())],
        selections={_requirement().requirement_ref: _offer().source_ref}, test_type="backtest")
    yield repo, remote, service, binding, route
    server.shutdown(); server.server_close(); thread.join()


def _job(repo, binding):
    run_spec = {"data_requirements": [asdict(_requirement())]}
    repo.create(JobRecord(job_id="node-test", run_id="run", owner="alice", workspace_id="ws",
        kind="backtest", status=JobStatus.SUBMITTED, deployment_id=binding["route_id"],
        service_port=8000, source_revision="test-build", job_spec={"run_spec":run_spec, "execution_binding": binding},
        run_spec_hash=canonical_hash(run_spec)))
    repo.claim_planning("node-test", 1)


def test_signed_job_plan_claim_progress_and_terminal_share_one_authority(transport):
    repo, remote, _, binding, _ = transport
    _job(repo, binding); remote.attempts["node-test"] = 1
    assert remote.load("node-test").status is JobStatus.PLANNING
    remote.set_execution_plan("node-test", plan={"kind":"backtest"}, notices=[], requires_confirmation=False)
    assert remote.claim_attempt("node-test", 1).status is JobStatus.RUNNING
    assert remote.claim_attempt("node-test", 1) is None
    assert remote.heartbeat_attempt("node-test", 1, "ignored")
    assert not remote.cancel_requested("node-test", 1)
    assert remote.record_progress("node-test", 1, sequence=1, phase="replay", completed=1,total=2,percent=50)
    assert remote.transition("node-test", JobStatus.SUCCEEDED, result_summary={"ok":True}).status is JobStatus.SUCCEEDED
    assert repo.require("node-test").result_summary == {"ok":True}
    assert not hasattr(remote, "db_path")


def test_wrong_node_and_other_manager_are_rejected_before_job_access(transport, tmp_path):
    repo, remote, service, binding, _ = transport
    _job(repo, binding)
    with pytest.raises(PermissionError):
        service.operation("node-c", {"job_id":"node-test","attempt":1,"action":"load"})
    from dataclasses import replace
    descriptor = {**remote.descriptor, "target": {**remote.descriptor["target"], "manager_id":"manager-other"}}
    with pytest.raises(urllib.error.HTTPError) as error:
        remote.client.post_json("/api/federation/execution/register", descriptor)
    assert error.value.code == 403
    with pytest.raises(PermissionError):
        service.operation("node-b", {"job_id":"node-test","attempt":2,"action":"load"})


def test_node_result_bytes_are_verified_and_registered(transport, tmp_path):
    repo, remote, _, binding, _ = transport
    _job(repo, binding);remote.attempts["node-test"]=1
    remote.set_execution_plan("node-test", plan={"kind":"backtest"}, notices=[], requires_confirmation=False)
    remote.claim_attempt("node-test",1)
    path=tmp_path/"orders.csv";path.write_text("a,b\n1,2\n")
    remote._upload("node-test",path,"orders.csv")
    artifacts=repo.list_artifacts(job_id="node-test",owner="alice")
    assert artifacts[0]["size_bytes"] == path.stat().st_size
    with pytest.raises(urllib.error.HTTPError):
        remote._upload("node-test",path,"../outside.csv")


def test_execution_api_rejects_invalid_oidc_bearer(transport):
    from urllib.request import Request, urlopen
    _, remote, _, _, _=transport
    request=Request(remote.client.endpoint+"/api/federation/execution/register",data=b"{}",method="POST",
        headers={"Authorization":"Bearer invalid-token","Content-Type":"application/json"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urlopen(request)
    assert error.value.code==403


def test_saved_automatic_binding_is_revalidated_even_without_client_hash(transport, monkeypatch):
    from server.modules.single_factor_test import research_jobs, execution_nodes
    from server.services.research_run_context import RunRequestError
    _, _, service, binding, _ = transport
    product = _requirement().product_ref
    prepared = {'owner':'alice','analyses':['backtest'],
        'execution_selection':{'mode':'auto','manager_id':'manager-a','resolved_ref':'obsolete'},
        'run_spec':{'data_requirements':[asdict(_requirement())],
            'configuration':{'shared':{'product_selections':{'scope':{'paths':[product]}}}}}}
    monkeypatch.setattr(execution_nodes,'node_service',lambda:service)
    monkeypatch.setattr(research_jobs,'_prepare_local_research_run_request',lambda *a,**k:prepared)
    with pytest.raises(RunRequestError) as error:
        research_jobs._prepare_research_run_request({},owner='alice')
    assert error.value.status_code == 409
    assert error.value.details['code'] == 'execution_binding_changed'
    prepared['execution_selection']['resolved_ref']=canonical_hash(binding)
    assert research_jobs._prepare_research_run_request({},owner='alice')['execution_binding']==binding
