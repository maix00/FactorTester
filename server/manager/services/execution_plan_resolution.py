"""Resolve one ExecutionPlan input snapshot; metadata only, no Job creation."""
from server.jobs.assurance import canonical_hash
from server.services.execution_plans import encode
from server.services.research_configurations import load_workspace_configuration
from server.services.frozen_product_scope import freeze_product_scope
from server.modules.single_factor_test.execution_nodes import (
    visible_targets,peer_execution_route,requirements_for_configuration,bind_prepared_execution,
)


def resolve(state, *, owner, request):
    workspace=str(request.get('workspace_id') or '')
    stored=load_workspace_configuration(workspace_id=workspace,owner=owner)
    if stored is None:raise PermissionError('workspace is unavailable')
    plan=request['execution_plan'];payload=encode(plan)
    selection=plan['execution'];manager=selection.get('manager_id') or state.server_id
    if not selection.get('bundles'):raise ValueError('select at least one Bundle')
    configuration={**stored,'payload':payload}
    if manager==state.server_id:
        directory=visible_targets(owner);route=None
    else:
        route=peer_execution_route(state,manager)
        directory=state.federation_gateway.public_data(route,kind='execution',operation='targets',principal=owner)['targets']
    bundle_keys={(item['bundle_id'],item['owner']) for item in selection['bundles']}
    known=frozenset(offer['product_ref'] for row in directory for offer in row['offers']
        if (offer['installation']['bundle_id'],offer['installation']['owner']) in bundle_keys)
    frozen=freeze_product_scope(configuration,owner=owner,analyses=plan['run_spec']['analyses'],known_product_refs=known)
    requirements=requirements_for_configuration(frozen,selection,directory)
    prepared={'owner':owner,'analyses':plan['run_spec']['analyses'],
        'run_spec':{'configuration':frozen['payload'],'data_requirements':requirements}}
    if route is None:
        binding=bind_prepared_execution(prepared,selection)
    else:
        binding=state.federation_gateway.public_data(route,kind='execution',operation='resolve-selection',principal=owner,
            payload={'prepared':prepared,'selection':selection})['binding']
    return {'success':True,'binding':binding,'binding_ref':canonical_hash(binding)}
