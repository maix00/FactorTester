"""Automatic location selection obeys the same explicit binding contract."""
from dataclasses import asdict,replace
import pytest
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.modules.single_factor_test import execution_nodes
from tests.server.test_execution_data_binding import _offer,_target,_requirement


@pytest.fixture
def matching(tmp_path,monkeypatch):
    service=ExecutionNodeService(JobRepository(tmp_path/'jobs.sqlite'),manager_id='manager-a')
    offer=_offer();runtime={"member_key":"minute","adapter_id":"v1","frequency":"MIN1","instrument_scope":"physical_contract","clock_policy":"bar-end"}
    service.register('node-b',{"target":asdict(_target()),"service_port":8000,"offers":[asdict(offer)],"runtime_adapters":{offer.source_ref:runtime}})
    monkeypatch.setattr(execution_nodes,'node_service',lambda:service)
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
