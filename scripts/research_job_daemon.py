#!/usr/bin/env python3
"""Run the single scheduler daemon for one FactorTester deployment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.jobs.ipc import JobDaemonServer
from server.jobs.artifacts import cleanup_staging_files
from server.jobs.repository import JobRepository
from server.jobs.scheduling import ResearchJobScheduler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--planner-workers", type=int, default=1)
    parser.add_argument("--execution-workers", type=int, default=2)
    args = parser.parse_args()
    cleanup_staging_files(
        max_age_seconds=float(os.environ.get("GTHT_JOB_STAGING_MAX_AGE_SECONDS", "3600"))
    )
    scheduler = ResearchJobScheduler(
        repository=JobRepository(),
        deployment_id=args.deployment_id,
        planner_workers=max(1, args.planner_workers),
        execution_workers=max(1, args.execution_workers),
        cancel_grace_seconds=float(os.environ.get("GTHT_JOB_CANCEL_GRACE_SECONDS", "2")),
    )
    server = JobDaemonServer(socket_path=Path(args.socket), scheduler=scheduler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
