#!/usr/bin/env python3
"""Run the planning-only sidecar for one FactorTester service."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    from server.jobs.ipc import JobDaemonServer
    from server.jobs.planning.daemon import PlanningDaemon
    from server.jobs.repository import JobRepository

    repository = JobRepository()
    publisher = None
    if os.environ.get("FACTORTESTER_BROKER_URL", "").strip():
        from server.jobs.dispatch.dispatcher import publisher_from_env

        publisher = publisher_from_env()
    daemon = PlanningDaemon(
        repository=repository, deployment_id=args.deployment_id,
        publisher=publisher,
        target_online=repository.worker_target_online,
    )
    JobDaemonServer(socket_path=Path(args.socket), scheduler=daemon).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
