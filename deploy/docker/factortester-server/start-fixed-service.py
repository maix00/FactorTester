#!/usr/bin/env python3
"""Start the deployment's fixed service after Manager readiness."""

from __future__ import annotations

import argparse
import json
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(
    url: str,
    token: str,
    *,
    form: dict[str, str] | None = None,
) -> dict:
    data = urlencode(form).encode("ascii") if form is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST" if form is not None else "GET",
    )
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urlopen(request, timeout=5, context=context) as response:
        raw = response.read()
    value = json.loads(raw) if raw else {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager", required=True)
    parser.add_argument("--capability-file", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    deadline = time.monotonic() + max(5, args.timeout)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            token = args.capability_file.read_text(encoding="ascii").strip()
            payload = request_json(
                f"{args.manager.rstrip('/')}/api/worktrees", token,
            )
            target = next(
                item for item in payload.get("worktrees", [])
                if int(item.get("port") or 0) == args.port
                and str(item.get("branch") or "") == args.branch
            )
            if not bool(target.get("online")):
                request_json(
                    f"{args.manager.rstrip('/')}/start",
                    token,
                    form={"instance_id": str(target["instance_id"])},
                )
            print(
                f"Fixed {args.branch} service {args.port} is managed by "
                f"{target['instance_id']}",
                flush=True,
            )
            return 0
        except (
            HTTPError,
            URLError,
            OSError,
            ValueError,
            KeyError,
            StopIteration,
        ) as exc:
            last_error = exc
            time.sleep(1)
    raise TimeoutError(
        f"Manager did not start fixed service {args.branch}:{args.port}: "
        f"{last_error}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
