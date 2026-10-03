from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.commands.client_profile import client_profile
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release import profile_sync


def test_profile_sync_command_keeps_local_success_distinct_from_pending_pg(
    tmp_path, monkeypatch,
) -> None:
    root = tmp_path / "client"
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(root))
    LocalProfileStore(root).save(new_local_profile(
        profile_id="maxa",
        display_name="Max A",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
        principal_ref="user1",
    ))

    class OfflineClient:
        def __init__(self, _session):
            pass

        def current_principal(self):
            return {"success": True, "username": "user1"}

        def sync_profile(self, profile):
            assert profile["profile_id"] == "maxa"
            return {
                "status": "pending",
                "synced": False,
                "pending": True,
                "reason": "control database is unavailable",
            }

    # ``client_profile`` delegates to the extracted release-layer sync
    # module; patch the dependency where that module resolves it.
    monkeypatch.setattr(profile_sync, "FactorTesterClient", OfflineClient)
    result = CliRunner().invoke(client_profile, ["sync", "maxa"])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["synced"] is False
    assert value["profiles"][0]["status"] == "pending"
