import json
from pathlib import Path
from scripts.migrations.migrate_factor_versions_to_couchdb import main


def test_dry_run_counts_factor_versions(tmp_path):
    spec = {"run_spec": {"configuration": {"shared": {"factors": [
        {"ref": "factor:v2:" + "a" * 43, "owner_ref": "alice"},
    ]}}}}
    path = tmp_path / "run.json"; path.write_text(json.dumps(spec))
    assert main(["--run-spec", str(path), "--couchdb-url", "http://x", "--dry-run"]) == 0
