import json

from click.testing import CliRunner

from tools.cli.commands import client_local_research


def call(root, request, *, identity="alice", profile="self"):
    payload = {"binding": {"issuer": "https://id.test/realm", "identity_id": identity},
               "profile": {"profile_id": profile, "display_name": "Alice"}, "request": request}
    return CliRunner().invoke(client_local_research.local_research_request, [], input=json.dumps(payload),
                              env={"TRADERESEARCH_CLIENT_ROOT": str(root)})


def test_local_transport_real_catalog_is_scoped_and_idempotent(tmp_path):
    create = {"action": "create", "profile_id": "self", "title": "Test", "description": "", "operation_id": "op1"}
    first = call(tmp_path, create)
    assert first.exit_code == 0, first.output
    repeated = call(tmp_path, create)
    assert json.loads(first.output)["research"] == json.loads(repeated.output)["research"]
    listing = {"action": "list", "profile_id": "self", "limit": 20, "offset": 0}
    assert len(json.loads(call(tmp_path, listing).output)["researches"]) == 1
    assert json.loads(call(tmp_path, listing, identity="other").output)["researches"] == []


def test_local_transport_rejects_profile_and_request_identity_injection(tmp_path):
    assert call(tmp_path, {"action": "capabilities"}, profile="other").exit_code != 0
    assert call(tmp_path, {"action": "capabilities", "identity_id": "other"}).exit_code != 0
    assert CliRunner().invoke(client_local_research.local_research_request, [], input="x" * 32769).exit_code != 0
