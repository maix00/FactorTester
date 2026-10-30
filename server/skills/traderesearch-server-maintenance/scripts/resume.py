#!/usr/bin/env python3
"""Request the bounded, authorized Server Maintenance resume packet."""

from __future__ import annotations

import argparse
import json

from tools.cli.core.context import client_from_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", required=True)
    args = parser.parse_args()
    packet = client_from_config().resume_agent(
        args.agent_id,
        role="server_maintenance",
    )
    print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
