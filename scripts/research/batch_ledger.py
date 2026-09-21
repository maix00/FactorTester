"""Preflight and record research matrix jobs without mutable /tmp result files.

The server's Job remains authoritative.  This ledger stores only the immutable
batch plan and Job pointers needed to resume an interrupted agent run.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


_BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_REF_PREFIX = "factor:v2:"
_CATALOG_MAX_AGE = dt.timedelta(minutes=10)


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _catalog_refs(catalog: dict, *, now: dt.datetime) -> dict[tuple[str, str], str]:
    timestamp = dt.datetime.fromisoformat(str(catalog.get("generated_at") or ""))
    if timestamp.tzinfo is None:
        raise ValueError("catalog generated_at needs a timezone")
    age = now - timestamp.astimezone(dt.timezone.utc)
    if age < -dt.timedelta(minutes=1) or age > _CATALOG_MAX_AGE:
        raise ValueError("factor catalog is not a current server snapshot")
    factors = catalog.get("factors")
    if not isinstance(factors, list):
        raise ValueError("catalog factors must be a list")
    refs: dict[tuple[str, str], str] = {}
    for factor in factors:
        if not isinstance(factor, dict):
            raise ValueError("catalog factor must be an object")
        key = (str(factor.get("owner_ref") or "").strip(),
               str(factor.get("alias") or "").strip())
        ref = str(factor.get("ref") or "").strip()
        if not all(key) or not ref.startswith(_REF_PREFIX):
            raise ValueError("catalog factor has an incomplete identity")
        if key in refs and refs[key] != ref:
            raise ValueError(f"catalog has ambiguous factor: {key}")
        refs[key] = ref
    return refs


def validate_plan(plan: dict, catalog: dict, *, now: dt.datetime | None = None) -> dict:
    """Return a canonical plan only if every alias resolves to its current ref."""
    now = now or dt.datetime.now(dt.timezone.utc)
    batch_id = str(plan.get("batch_id") or "")
    server_id = str(plan.get("server_id") or "").strip()
    if not _BATCH_ID.fullmatch(batch_id) or not server_id:
        raise ValueError("batch_id or server_id is invalid")
    if server_id != str(catalog.get("server_id") or "").strip():
        raise ValueError("plan and catalog refer to different servers")
    current = _catalog_refs(catalog, now=now)
    rows = plan.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("plan rows must be a nonempty list")
    normalized = []
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("plan row must be an object")
        key = str(row.get("key") or "").strip()
        owner = str(row.get("owner_ref") or "").strip()
        alias = str(row.get("factor_alias") or "").strip()
        ref = str(row.get("factor_ref") or "").strip()
        run_spec_hash = str(row.get("run_spec_hash") or "").strip()
        if not key or key in keys:
            raise ValueError(f"duplicate or empty matrix key: {key}")
        keys.add(key)
        if (not owner or not alias or not ref.startswith(_REF_PREFIX)
                or not run_spec_hash.startswith("sha256:")):
            raise ValueError(f"incomplete factor binding: {key}")
        actual = current.get((owner, alias))
        if actual != ref:
            raise ValueError(f"stale or missing factor ref for {key}: {alias}")
        normalized.append({"key": key, "owner_ref": owner,
                           "factor_alias": alias, "factor_ref": ref,
                           "run_spec_hash": run_spec_hash})
    return {"batch_id": batch_id, "server_id": server_id, "rows": normalized}


def _durable_dir(path: Path) -> Path:
    result = path.expanduser().resolve()
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
    }
    if any(result.is_relative_to(root) for root in temporary_roots):
        raise ValueError("ledger directory must not be inside the temporary directory")
    if any((parent / ".git").exists() for parent in (result, *result.parents)):
        raise ValueError("ledger directory must be outside the Git repository")
    result.mkdir(parents=True, exist_ok=True)
    return result


@contextlib.contextmanager
def _locked(path: Path):
    with (path.with_suffix(path.suffix + ".lock")).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".batch-ledger-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(_canonical(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(manifest: Path, catalog_path: Path, ledger_dir: Path) -> Path:
    plan = validate_plan(_load(manifest), _load(catalog_path))
    destination = _durable_dir(ledger_dir) / f"{plan['batch_id']}.json"
    planned = {"schema_version": 1, "plan": plan, "plan_sha256": _digest(plan),
               "jobs": {}}
    with _locked(destination):
        if destination.exists():
            existing = _load(destination)
            if existing.get("plan_sha256") != planned["plan_sha256"]:
                raise ValueError("batch_id is already bound to a different plan")
        else:
            _atomic_write(destination, planned)
    return destination


def record_job(ledger: Path, catalog_path: Path, *, key: str, run_id: str,
               job_id: str, run_spec_hash: str) -> dict:
    if not all((key, run_id, job_id, run_spec_hash)):
        raise ValueError("key, run_id, job_id and run_spec_hash are required")
    ledger = ledger.expanduser().resolve()
    _durable_dir(ledger.parent)
    with _locked(ledger):
        value = _load(ledger)
        plan = validate_plan(value["plan"], _load(catalog_path))
        if _digest(plan) != value.get("plan_sha256"):
            raise ValueError("ledger plan digest changed")
        planned_rows = {row["key"]: row for row in plan["rows"]}
        if key not in planned_rows:
            raise ValueError(f"matrix key is not in this batch: {key}")
        if run_spec_hash != planned_rows[key]["run_spec_hash"]:
            raise ValueError(f"RunSpec hash differs from the preflight plan: {key}")
        binding = {"run_id": run_id, "job_id": job_id,
                   "run_spec_hash": run_spec_hash}
        previous = value["jobs"].get(key)
        if previous is not None and previous != binding:
            raise ValueError(f"matrix key already has another Job: {key}")
        if any(
            other_key != key and job.get("job_id") == job_id
            for other_key, job in value["jobs"].items()
        ):
            raise ValueError(f"Job is already assigned to another matrix key: {job_id}")
        value["jobs"][key] = binding
        _atomic_write(ledger, value)
        return binding


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="validate current refs and create one batch ledger")
    init.add_argument("--manifest", required=True, type=Path)
    init.add_argument("--catalog", required=True, type=Path)
    init.add_argument("--ledger-dir", required=True, type=Path)
    record = commands.add_parser("record", help="bind one matrix key to a durable server Job")
    record.add_argument("--ledger", required=True, type=Path)
    record.add_argument("--catalog", required=True, type=Path)
    for name in ("key", "run-id", "job-id", "run-spec-hash"):
        record.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            print(initialize(args.manifest, args.catalog, args.ledger_dir))
        else:
            print(json.dumps(record_job(
                args.ledger, args.catalog, key=args.key, run_id=args.run_id,
                job_id=args.job_id, run_spec_hash=args.run_spec_hash,
            ), ensure_ascii=False))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(2, f"batch ledger: {error}\n")


if __name__ == "__main__":
    main()
