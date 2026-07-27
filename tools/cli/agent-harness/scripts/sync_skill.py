#!/usr/bin/env python3
"""Synchronize the packaged FactorTester research Skill from its canonical copy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


_RELATIVE_CANONICAL = Path("skills/cli-anything-factortester-research/SKILL.md")
_RELATIVE_PACKAGED = Path(
    "tools/cli/agent-harness/cli_anything/factortester_research/skills/SKILL.md"
)
_RELATIVE_HARNESS = Path("tools/cli/agent-harness/cli_anything/factortester_research")
_RELATIVE_CAPABILITIES = _RELATIVE_HARNESS / "resources/capabilities.v1.json"
_RELATIVE_PROVIDER_LOCKS = _RELATIVE_HARNESS / "resources/provider-locks.v1.json"
_LOCAL_PROVIDER = "factortester-research-package"


def repository_root(start: Path | None = None) -> Path:
    """Find the repository root without relying on the current directory."""
    current = (start or Path(__file__)).resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists() and (parent / _RELATIVE_CANONICAL).is_file():
            return parent
    raise RuntimeError("FactorTester repository root was not found")


def skill_paths(root: Path) -> tuple[Path, Path]:
    return root / _RELATIVE_CANONICAL, root / _RELATIVE_PACKAGED


def sync_skill(root: Path) -> bool:
    """Write the package copy from the canonical source; return whether changed."""
    canonical, packaged = skill_paths(root)
    content = canonical.read_bytes()
    if packaged.is_file() and packaged.read_bytes() == content:
        return False
    packaged.parent.mkdir(parents=True, exist_ok=True)
    packaged.write_bytes(content)
    return True


def check_skill(root: Path) -> bool:
    """Return whether the packaged copy exactly matches its canonical source."""
    canonical, packaged = skill_paths(root)
    return packaged.is_file() and packaged.read_bytes() == canonical.read_bytes()


def _source_manifest(root: Path, source_paths: list[str]) -> str:
    manifest = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in sorted(source_paths)
    }
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _local_lock_rows(root: Path) -> tuple[dict, dict[str, dict]]:
    capabilities = json.loads((root / _RELATIVE_CAPABILITIES).read_text("utf-8"))
    locks = json.loads((root / _RELATIVE_PROVIDER_LOCKS).read_text("utf-8"))
    providers = {
        str(item.get("implementation_id") or ""): str(item.get("provider") or "")
        for capability in capabilities.get("capabilities") or []
        for item in capability.get("implementations") or []
        if isinstance(item, dict)
    }
    return locks, {
        identifier: value
        for identifier, value in (locks.get("implementations") or {}).items()
        if providers.get(identifier) == _LOCAL_PROVIDER
    }


def local_provider_lock_mismatches(root: Path) -> list[str]:
    """Return locally packaged skills whose approved source fingerprints drift."""
    _, rows = _local_lock_rows(root)
    harness = root / _RELATIVE_HARNESS
    mismatches = []
    for identifier, lock in rows.items():
        paths = lock.get("source_paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            mismatches.append(identifier)
            continue
        if _source_manifest(harness, paths) != lock.get("sha256"):
            mismatches.append(identifier)
    return sorted(mismatches)


def refresh_local_provider_locks(root: Path) -> bool:
    """Refresh reviewed local-skill fingerprints after an explicit content change."""
    locks, rows = _local_lock_rows(root)
    harness = root / _RELATIVE_HARNESS
    changed = False
    for identifier, lock in rows.items():
        paths = lock.get("source_paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise RuntimeError(f"invalid source paths for {identifier}")
        digest = _source_manifest(harness, paths)
        if lock.get("sha256") != digest:
            locks["implementations"][identifier]["sha256"] = digest
            changed = True
    if changed:
        (root / _RELATIVE_PROVIDER_LOCKS).write_text(
            json.dumps(locks, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on drift")
    mode.add_argument("--write", action="store_true", help="refresh package copy")
    mode.add_argument(
        "--refresh-local-provider-locks", action="store_true",
        help="explicitly refresh reviewed hashes for bundled local skills",
    )
    parser.add_argument("--repo", type=Path, help="FactorTester repository root")
    args = parser.parse_args(argv)
    root = args.repo.resolve() if args.repo else repository_root()
    if args.write:
        print("updated" if sync_skill(root) else "unchanged")
        return 0
    if args.refresh_local_provider_locks:
        print("updated" if refresh_local_provider_locks(root) else "unchanged")
        return 0
    mismatches = local_provider_lock_mismatches(root)
    if check_skill(root) and not mismatches:
        print("in-sync")
        return 0
    if not check_skill(root):
        print("Skill copies differ; run sync_skill.py --write before committing", file=sys.stderr)
    if mismatches:
        print(
            "Local provider Skill locks differ: " + ", ".join(mismatches)
            + "; review and run sync_skill.py --refresh-local-provider-locks",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
