"""Real HTTP control/data-plane acceptance with isolated runtime and Profile stores."""
from contextlib import contextmanager
import threading

from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.objects.adapters.public_research import PublicResearchOriginAdapter
from server.manager.objects.adapters.public_research_destination import PublicResearchDestinationAdapter
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.collaboration import publish_local_branch, fork_remote_branch
from tools.cli.release.research_reporting.report_space import initialize_report_space
from tools.cli.release.research_reporting.authoring.tree_model import add_component, load_snapshot
from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore


@contextmanager
def running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_client_profile_fork_upload_over_real_control_and_object_http(tmp_path):
    state = manager.ManagerState(tmp_path / 'repo', 'python', server_id='collaboration-http',
                                 state_root=tmp_path / 'manager-state', data_root=tmp_path / 'data')
    catalog = state.research_catalog
    rid = catalog.create_research(owner_ref='alice', title='Shared')['research_id']
    ws = catalog.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='self', title='Owner')
    report = catalog.register_report(rid, actor='alice', report_id='http-report', title='Shared',
                                     profile_ref='self', workspace_id=ws['workspace_id'])
    catalog.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    objects = PublicResearchObjectStore(state.public_research)
    runtime = DataPlaneRuntime(server_id=state.server_id, transfer_database=state.transfer_database_path,
                               staging_root=state.transfer_submission_root,
                               origin_resolver=PublicResearchOriginAdapter(objects),
                               destination_committer=PublicResearchDestinationAdapter(objects))
    data = ClientDataPlaneHTTPServer(('127.0.0.1', 0), runtime=runtime)
    handler = type('CollaborationHandler', (manager.Handler,), {'state': state})
    control = manager.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    origin = f'http://127.0.0.1:{control.server_address[1]}'
    state.configure_data_plane(client_host='127.0.0.1', client_port=data.server_address[1],
                               client_control_endpoint=origin,
                               client_data_endpoint=f'http://127.0.0.1:{data.server_address[1]}')
    stores, clients = {}, {}
    for user in ('alice', 'bob'):
        token = 'isolated-' + user
        state._sessions[state._token_hash(token)] = (user, 'user', float('inf'))
        clients[user] = FactorTesterClient(HttpSession(origin, bearer_token=token, persist_cookies=False))
        store = LocalProfileStore(tmp_path / user)
        profile = new_local_profile(profile_id='self', display_name=user, server_url=origin,
                                    workspace_root=tmp_path / user / 'workspace')
        profile['session_binding'] = {'principal_ref': user, 'session_ref': 'session-binding:test'}
        store.save(profile)
        stores[user] = store
    initialized = initialize_report_space(stores['alice'], 'self', report)
    package_id = initialized['report_workspace_id']
    package = tmp_path / 'alice/workspace/research' / package_id
    add_component(package_root=package, branch_id='main', component_id='chapter', kind='chapter',
                  title='Real HTTP', parent_id=None, body='', content=None, display_kind='')
    with running(data), running(control):
        published = publish_local_branch(clients['alice'], stores['alice'], profile_id='self',
                                         report_workspace_id=package_id, branch_id='main')
        assert published['status'] == 'synced', published
        copied = fork_remote_branch(clients['bob'], stores['bob'], profile_id='self', report_id='http-report',
                                     source_branch_id='main', branch_id='bob-review')
        assert copied['status'] == 'synced', copied
        branches = clients['alice'].report_branch_status('http-report')['branches']
        assert {b['branch_id'] for b in branches} == {'main', 'bob-review'}
        assert {b['principal_ref'] for b in branches} == {'alice', 'bob'}
        target = tmp_path / 'bob/workspace/research' / copied['report_workspace_id']
        assert load_snapshot(package_root=target, branch_id='bob-review')['components'][0]['title'] == 'Real HTTP'
