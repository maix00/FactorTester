"""Automatic location selection obeys the same explicit binding contract."""
from dataclasses import asdict,replace
from types import SimpleNamespace
import pytest
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.modules.single_factor_test import execution_nodes
from tests.server.test_execution_data_binding import _offer,_target,_requirement


@pytest.fixture
def matching(tmp_path,monkeypatch):
    from server.identity import keycloak_authorization as authz
    service=ExecutionNodeService(JobRepository(tmp_path/'jobs.sqlite'),manager_id='manager-a')
    offer=_offer();runtime={"member_key":"minute","adapter_id":"v1","frequency":"MIN1","instrument_scope":"physical_contract","clock_policy":"bar-end"}
    service.register('node-b',{"target":asdict(_target()),"service_port":8000,"offers":[asdict(offer)],"runtime_adapters":{offer.source_ref:runtime}})
    monkeypatch.setattr(execution_nodes,'node_service',lambda:service)
    monkeypatch.setattr(authz, 'keycloak_request_identity', lambda: SimpleNamespace(username='alice', token='user-token'))
    monkeypatch.setattr(authz, 'keycloak_authorized_many', lambda _token, *, permissions, use_cache:
        {(uri, scope): True for uri, _name, scope in permissions} if use_cache is False else pytest.fail('node grants must be live'))
    prepared={"owner":"alice","analyses":["backtest"],"run_spec":{"data_requirements":[asdict(_requirement())],
        "configuration":{"shared":{"product_selections":{"scope":{"paths":["T.CFE"]}}}}}}
    return prepared


def test_auto_uses_compatible_node_and_freezes_actual_installation(matching):
    bound=execution_nodes.bind_prepared_execution(matching,{"mode":"auto","manager_id":"manager-a"})
    assert bound['target']['node_id']=='node-b'
    assert bound['inputs'][0]['source_ref']==_offer().source_ref
    assert bound['inputs'][0]['requirement']==asdict(_requirement())


def test_auto_rejects_coverage_gaps_without_altering_requirements(matching):
    matching['run_spec']['data_requirements'][0]['end_ns']=400
    with pytest.raises(ValueError,match='no authorized online node'):
        execution_nodes.bind_prepared_execution(matching,{"mode":"auto","manager_id":"manager-a"})
    assert matching['run_spec']['data_requirements'][0]['end_ns']==400


def test_auto_cannot_change_manager_scope(matching):
    with pytest.raises(PermissionError):
        execution_nodes.bind_prepared_execution(matching,{"mode":"auto","manager_id":"manager-other"})


def test_auto_does_not_read_another_users_installations(matching,monkeypatch):
    service=execution_nodes.node_service()
    other=replace(_offer(),installation=replace(_offer().installation,owner='bob'))
    monkeypatch.setattr(service,'directory',lambda:[{"deployment_id":"r","service_port":8000,"online":True,"expires_at":1,
        "capabilities":{"execution_target":asdict(_target()),"offers":[asdict(other)]}}])
    with pytest.raises(ValueError,match='no authorized online node'):
        execution_nodes.bind_prepared_execution(matching,{"mode":"auto","manager_id":"manager-a"})


def test_node_revocation_after_selection_hides_it_and_rejects_binding(matching, monkeypatch):
    from server.identity import keycloak_authorization as authz
    permission = {"allowed": True}
    def check(_token, *, permissions, use_cache):
        assert use_cache is False
        return {(uri, scope): permission["allowed"] for uri, _name, scope in permissions}
    monkeypatch.setattr(authz, "keycloak_authorized_many", check)
    assert execution_nodes.visible_targets("alice")[0]["target"]["node_id"] == "node-b"
    selected = {"mode": "auto", "manager_id": "manager-a"}
    assert execution_nodes.bind_prepared_execution(matching, selected)["target"]["node_id"] == "node-b"
    permission["allowed"] = False  # Same user token, before preview/submission.
    assert execution_nodes.visible_targets("alice") == []
    with pytest.raises(ValueError, match="no authorized online node"):
        execution_nodes.bind_prepared_execution(matching, selected)


def test_node_authorization_outage_fails_closed(matching, monkeypatch):
    from server.identity import keycloak_authorization as authz
    def offline(*_args, **_kwargs):
        raise authz.AuthorizationUnavailable("Keycloak unavailable")
    monkeypatch.setattr(authz, "keycloak_authorized_many", offline)
    with pytest.raises(authz.AuthorizationUnavailable):
        execution_nodes.visible_targets("alice")
    with pytest.raises(authz.AuthorizationUnavailable):
        execution_nodes.bind_prepared_execution(matching, {"mode": "auto", "manager_id": "manager-a"})


def test_visible_targets_filters_nodes_even_when_bundles_are_visible(matching, monkeypatch):
    from server.identity import keycloak_authorization as authz
    service = execution_nodes.node_service()
    original = service.directory()[0]
    other = {**original, "deployment_id": "node-c-route", "capabilities": {
        **original["capabilities"], "execution_target": {**original["capabilities"]["execution_target"],
                                                            "node_id": "node-c"}}}
    monkeypatch.setattr(service, "directory", lambda: [original, other])
    allowed_uri = authz.keycloak_resource_uri("execution_node",
        execution_nodes.execution_node_resource_ref("manager-a", "node-b"))
    calls = []
    def check(_token, *, permissions, use_cache):
        calls.append(permissions)
        return {(uri, scope): uri == allowed_uri for uri, _name, scope in permissions}
    monkeypatch.setattr(authz, "keycloak_authorized_many", check)
    assert [row["target"]["node_id"] for row in execution_nodes.visible_targets("alice")] == ["node-b"]
    assert len(calls) == 1 and len(calls[0]) == 2
