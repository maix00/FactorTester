"""A matrix agent must not reuse stale refs or overwrite another batch's Jobs."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.research import batch_ledger


def _allow_pytest_temp(monkeypatch):
    # The ledger tests need pytest's temporary directory; the separate policy
    # test exercises the actual durability check unchanged.
    def directory(path):
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()
    monkeypatch.setattr(batch_ledger, "_durable_dir", directory)


def _inputs(tmp_path: Path, *, batch_id="T-20260921"):
    now = dt.datetime.now(dt.timezone.utc)
    row = {"key": "T/DFP/20d", "owner_ref": "principal:alice",
           "factor_alias": "Signal|N:20d", "factor_ref": "factor:v2:CURRENT",
           "run_spec_hash": "sha256:one"}
    plan = {"batch_id": batch_id, "server_id": "public-main", "rows": [row]}
    catalog = {"server_id": "public-main", "generated_at": now.isoformat(),
               "factors": [{"owner_ref": row["owner_ref"],
                            "alias": row["factor_alias"], "ref": row["factor_ref"]}]}
    manifest = tmp_path / "plan.json"
    snapshot = tmp_path / "catalog.json"
    manifest.write_text(json.dumps(plan), encoding="utf-8")
    snapshot.write_text(json.dumps(catalog), encoding="utf-8")
    return manifest, snapshot, plan, catalog


def test_init_and_record_are_idempotent_but_never_overwrite_a_job(tmp_path, monkeypatch):
    _allow_pytest_temp(monkeypatch)
    manifest, snapshot, _, _ = _inputs(tmp_path)
    directory = tmp_path / "durable"
    ledger = batch_ledger.initialize(manifest, snapshot, directory)
    assert batch_ledger.initialize(manifest, snapshot, directory) == ledger
    binding = {"key": "T/DFP/20d", "run_id": "run-1", "job_id": "job-1",
               "run_spec_hash": "sha256:one"}
    assert batch_ledger.record_job(ledger, snapshot, **binding)["job_id"] == "job-1"
    batch_ledger.record_job(ledger, snapshot, **binding)
    with pytest.raises(ValueError, match="already has another Job"):
        batch_ledger.record_job(ledger, snapshot, **{**binding, "job_id": "job-2"})
    with pytest.raises(ValueError, match="RunSpec hash differs"):
        batch_ledger.record_job(ledger, snapshot, **{**binding, "run_spec_hash": "sha256:old"})
    assert json.loads(ledger.read_text())["jobs"]["T/DFP/20d"]["job_id"] == "job-1"


def test_stale_or_ambiguous_factor_ref_is_rejected(tmp_path):
    manifest, snapshot, plan, catalog = _inputs(tmp_path)
    plan["rows"][0]["factor_ref"] = "factor:v2:OLD"
    with pytest.raises(ValueError, match="stale or missing factor ref"):
        batch_ledger.validate_plan(plan, catalog)
    plan["rows"][0]["factor_ref"] = "factor:v2:CURRENT"
    plan["rows"].append(dict(plan["rows"][0]))
    with pytest.raises(ValueError, match="duplicate or empty matrix key"):
        batch_ledger.validate_plan(plan, catalog)
    catalog["factors"].append({**catalog["factors"][0], "ref": "factor:v2:OTHER"})
    with pytest.raises(ValueError, match="ambiguous factor"):
        batch_ledger.validate_plan({**plan, "rows": plan["rows"][:1]}, catalog)


def test_catalog_must_be_current_and_from_the_same_server(tmp_path):
    _, _, plan, catalog = _inputs(tmp_path)
    catalog["generated_at"] = (dt.datetime.now(dt.timezone.utc)
                                - dt.timedelta(minutes=11)).isoformat()
    with pytest.raises(ValueError, match="not a current server snapshot"):
        batch_ledger.validate_plan(plan, catalog)
    catalog["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    catalog["server_id"] = "another-server"
    with pytest.raises(ValueError, match="different servers"):
        batch_ledger.validate_plan(plan, catalog)


def test_batches_get_distinct_ledgers_and_changed_plan_cannot_reuse_id(tmp_path, monkeypatch):
    _allow_pytest_temp(monkeypatch)
    manifest, snapshot, plan, _ = _inputs(tmp_path)
    directory = tmp_path / "durable"
    first = batch_ledger.initialize(manifest, snapshot, directory)
    plan["batch_id"] = "TL-20260921"
    manifest.write_text(json.dumps(plan), encoding="utf-8")
    second = batch_ledger.initialize(manifest, snapshot, directory)
    assert first != second
    assert first.exists() and second.exists()
    plan["rows"][0]["key"] = "TL/DFP/20d"
    manifest.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="already bound to a different plan"):
        batch_ledger.initialize(manifest, snapshot, directory)


def test_one_job_cannot_silently_populate_two_matrix_keys(tmp_path, monkeypatch):
    _allow_pytest_temp(monkeypatch)
    manifest, snapshot, plan, _ = _inputs(tmp_path)
    plan["rows"].append({**plan["rows"][0], "key": "T/DFP/30d"})
    manifest.write_text(json.dumps(plan), encoding="utf-8")
    ledger = batch_ledger.initialize(manifest, snapshot, tmp_path / "durable")
    first = {"run_id": "run-1", "job_id": "job-1", "run_spec_hash": "sha256:one"}
    batch_ledger.record_job(ledger, snapshot, key="T/DFP/20d", **first)
    with pytest.raises(ValueError, match="already assigned to another matrix key"):
        batch_ledger.record_job(ledger, snapshot, key="T/DFP/30d", **first)


def test_temporary_directory_is_rejected(tmp_path):
    manifest, snapshot, _, _ = _inputs(tmp_path)
    with pytest.raises(ValueError, match="temporary directory"):
        batch_ledger.initialize(manifest, snapshot, Path("/tmp/research-batch-test"))


def test_cli_failure_preserves_nonzero_exit_status(tmp_path):
    manifest, snapshot, plan, _ = _inputs(tmp_path)
    plan["rows"][0]["factor_ref"] = "factor:v2:OLD"
    manifest.write_text(json.dumps(plan), encoding="utf-8")
    script = Path(batch_ledger.__file__)
    result = subprocess.run([
        sys.executable, str(script), "init", "--manifest", str(manifest),
        "--catalog", str(snapshot), "--ledger-dir", str(tmp_path / "durable"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "stale or missing factor ref" in result.stderr
