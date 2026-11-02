"""A retired graph cannot overwrite independently authored Profile branches.

Historical data is seeded with the offline migration fixture; no live legacy
ACL or synchronization path is installed to make these tests pass.
"""
import copy
import pytest
from scripts.test.historical_research_catalog import HistoricalResearchCatalog
from server.manager.storage.account_domain import AccountDomainSyncService


@pytest.mark.parametrize("deleted", [False, True])
def test_retired_remote_graph_preserves_each_profile_branch(tmp_path, deleted):
    path = tmp_path / "metadata.sqlite"
    catalog = HistoricalResearchCatalog(path)
    rid = catalog.create_research(owner_ref="alice", title="Local research")["research_id"]
    catalog.register_report(rid, actor="alice", report_id="report", profile_ref="self")
    for profile, marker in (("left", "a"), ("right", "b")):
        catalog.add_membership(rid, actor="alice", principal_ref="alice", profile_ref=profile, role="editor")
        catalog.create_workspace(rid, actor="alice", principal_ref="alice", profile_ref=profile)
        catalog.reserve_report_branch("report", actor="alice", profile_ref=profile, branch_id=profile)
        catalog.publish_report_branch("report", profile, actor="alice", profile_ref=profile,
            expected_generation=0, expected_revision="", generation=1, revision=marker*64,
            publication_id=marker*24, storage_server_id="local")
    before = copy.deepcopy(catalog.list_report_branches("report", viewer="alice"))
    sync = AccountDomainSyncService(sqlite_path=path, control_store=None, manager_id="local")
    assert sync.local.apply_remote({"principal":"alice", "entity_type":"research_catalog", "entity_id":rid,
        "payload":{"research":{"research_id":rid,"title":"Stale peer title"},"branches":[]},
        "revision":9,"deleted":deleted,"origin_manager_id":"peer"}) == "retired"
    assert catalog.get_research_summary(rid, viewer="alice")["title"] == "Local research"
    assert catalog.list_report_branches("report", viewer="alice") == before
    assert {row["branch_id"] for row in before} == {"left", "right"}
    assert len(sync.local.conflicts(principal="alice")) == 1
