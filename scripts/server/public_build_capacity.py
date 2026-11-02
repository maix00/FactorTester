#!/usr/bin/env python3
"""Check bounded build and snapshot headroom without deleting host data."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess


MIB = 1024**2
DEFAULT_RESERVE_MIB = 10 * 1024
DEFAULT_BUILD_MIB = 5 * 1024


def _existing(path: Path) -> Path:
    path = path.expanduser().resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def capacity_plan(*, root: Path, docker_root: Path, cache_root: Path,
                  reserve_mib: int, build_mib: int, snapshot_mib: int,
                  minimum_mib: int = 0) -> list[dict]:
    """Combine peak allocations sharing a filesystem, keeping a reserve on each."""
    if min(reserve_mib, build_mib, snapshot_mib, minimum_mib) < 0:
        raise ValueError("negative capacity budget")
    groups: dict[int, dict] = {}
    for kind, source, extra in (("host", root, 0), ("build", docker_root, build_mib),
                                ("snapshot", cache_root, snapshot_mib)):
        path = _existing(source)
        device = path.stat().st_dev
        group = groups.setdefault(device, {"path": str(path), "free_mib": shutil.disk_usage(path).free // MIB,
                                           "required_mib": reserve_mib, "uses": []})
        group["free_mib"] = min(group["free_mib"], shutil.disk_usage(path).free // MIB)
        group["required_mib"] += extra
        group["uses"].append(kind)
    for group in groups.values():
        group["required_mib"] = max(group["required_mib"], minimum_mib)
    return list(groups.values())


def check_memory(meminfo: Path = Path("/proc/meminfo")) -> None:
    if not meminfo.is_file():
        return
    available = next((int(line.split()[1]) // 1024 for line in meminfo.read_text().splitlines()
                      if line.startswith("MemAvailable:")), None)
    if available is None or available < 2048:
        raise RuntimeError("public build requires at least 2048 MiB available RAM")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=Path("/"))
    parser.add_argument("--snapshot-mib", type=int, default=2048)
    parser.add_argument("--build-mib", type=int, default=DEFAULT_BUILD_MIB)
    args = parser.parse_args()
    docker_root = subprocess.run(["docker", "info", "--format", "{{.DockerRootDir}}"], check=True,
                                 capture_output=True, text=True, timeout=30).stdout.strip()
    if not docker_root or not Path(docker_root).is_absolute():
        raise RuntimeError("unable to determine Docker storage location")
    configured = os.environ.get("FACTORTESTER_MIN_BUILD_FREE_GB", "")
    if configured and (not configured.isdigit() or int(configured) < 1):
        raise ValueError("invalid minimum build free space")
    minimum = int(configured) * 1024 if configured else 0
    budgets = capacity_plan(root=Path("/"), docker_root=Path(docker_root), cache_root=args.cache_root,
                            reserve_mib=DEFAULT_RESERVE_MIB, build_mib=args.build_mib,
                            snapshot_mib=args.snapshot_mib, minimum_mib=minimum)
    check_memory()
    for item in budgets:
        if item["free_mib"] < item["required_mib"]:
            raise RuntimeError(f"insufficient storage for {','.join(item['uses'])}: "
                               f"available {item['free_mib']} MiB, required {item['required_mib']} MiB")
    print("public build capacity verified:", "; ".join(
        f"{','.join(item['uses'])} free={item['free_mib']} MiB required={item['required_mib']} MiB"
        for item in budgets))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc)) from None
