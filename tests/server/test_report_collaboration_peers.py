"""Two Manager control surfaces and real peer HTTP; account store is isolated memory."""
from contextlib import ExitStack

from server.manager import runtime as manager
from server.manager.http.peer_handler import peer_control_handler
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.objects.adapters.public_research import PublicResearchOriginAdapter
from server.manager.objects.adapters.public_research_destination import PublicResearchDestinationAdapter
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession, HttpClientError
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.collaboration import publish_local_branch
from tools.cli.release.research_reporting.report_space import initialize_report_space
from tools.cli.release.research_reporting.authoring.tree_model import add_component
from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore
from tests.scripts.test_worktree_manager_account_domain_sync import MemoryControlStore
from tests.server.test_report_collaboration_http import running


def test_registered_branch_is_readable_through_other_manager_and_revocation_is_enforced(tmp_path):
    control_store = MemoryControlStore()
    nodes = []
    with ExitStack() as stack:
        for name in ('source', 'reader'):
            root = tmp_path / name
            state = manager.ManagerState(root / 'repo', 'python', server_id=name,
                                         state_root=root / 'state', data_root=root / 'data')
            state.account_domain_sync.control_store = control_store
            # Drive the real outbox/cursor synchronously, avoiding unrelated background workers.
            state.research_catalog.set_synchronizer(state.account_domain_sync)
            objects = PublicResearchObjectStore(state.public_research)
            runtime = DataPlaneRuntime(server_id=name, transfer_database=state.transfer_database_path,
                staging_root=state.transfer_submission_root, origin_resolver=PublicResearchOriginAdapter(objects),
                destination_committer=PublicResearchDestinationAdapter(objects))
            data = stack.enter_context(running(ClientDataPlaneHTTPServer(('127.0.0.1', 0), runtime=runtime)))
            handler = type('PeerReportHandler', (manager.Handler,), {'state': state})
            origin = stack.enter_context(running(manager.ThreadingHTTPServer(('127.0.0.1', 0), handler)))
            peer = stack.enter_context(running(manager.ThreadingHTTPServer(('127.0.0.1', 0), peer_control_handler(state))))
            state.configure_data_plane(client_host='127.0.0.1', client_port=int(data.rsplit(':', 1)[1]),
                                       client_control_endpoint=origin, client_data_endpoint=data)
            clients = {}
            for user in ('alice', 'bob'):
                token = name + '-isolated-' + user
                state._sessions[state._token_hash(token)] = (user, 'user', float('inf'))
                clients[user] = FactorTesterClient(HttpSession(origin, bearer_token=token, persist_cookies=False))
            nodes.append((state, origin, peer, clients))
        source, _, source_peer, source_clients = nodes[0]
        reader, _, _, reader_clients = nodes[1]
        reader.federation_registry.register({'server_id':'source', 'role':'main', 'ports':[],
            'endpoint':nodes[0][1], 'proxy_token':source.federation_proxy_token(),
            'transfer_node':{'peer_control_endpoint':source_peer}})
        catalog = source.research_catalog
        rid = catalog.create_research(owner_ref='alice', title='Cross Manager')['research_id']
        workspace = catalog.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='self')
        report = catalog.register_report(rid, actor='alice', report_id='peer-report', title='Peer report',
                                         profile_ref='self', workspace_id=workspace['workspace_id'])
        catalog.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
        store = LocalProfileStore(tmp_path / 'client')
        profile = new_local_profile(profile_id='self', display_name='Alice', server_url=nodes[0][1],
                                    workspace_root=tmp_path / 'workspace')
        profile['session_binding'] = {'principal_ref':'alice', 'session_ref':'session-binding:test'}
        store.save(profile)
        package_id = initialize_report_space(store, 'self', report)['report_workspace_id']
        add_component(package_root=tmp_path / 'workspace/research' / package_id, branch_id='main',
                      component_id='chapter', kind='chapter', title='Across servers', parent_id=None,
                      body='', content=None, display_kind='')
        published = publish_local_branch(source_clients['alice'], store, profile_id='self',
                                         report_workspace_id=package_id, branch_id='main')
        assert source.account_domain_sync.flush(principal='alice')['sent'] == 1
        assert reader.account_domain_sync.pull(principal='bob')['applied'] == 1
        branches = reader_clients['bob'].report_branch_status('peer-report')['branches']
        assert branches == source_clients['alice'].report_branch_status('peer-report')['branches']
        index = reader_clients['bob'].read_publication_branch(published['publication_id'])
        assert index['report_id'] == 'peer-report'
        assert index['authoring_bundle']['root_ref']
        assert index['chapters'][0]['title'] == 'Across servers'
        catalog.remove_membership(rid, actor='alice', principal_ref='bob', profile_ref='self')
        source.account_domain_sync.flush(principal='alice')
        reader.account_domain_sync.pull(principal='bob')
        import pytest
        with pytest.raises(HttpClientError) as denied:
            reader_clients['bob'].read_publication_branch(published['publication_id'])
        assert denied.value.status == 403
