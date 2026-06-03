#!/usr/bin/env python3
"""Run a small local UI for starting Flask from multiple git worktrees."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


MASTER_PORT = 8000
FEAT_PORT = 7999

# Matches branches named fix/issue-<N>-<slug> or fix/issue-<N>
_ISSUE_BRANCH_RE = re.compile(r'^fix/issue-(\d+)(?:-.*)?$')


def _extract_issue_number(branch: str) -> int | None:
    m = _ISSUE_BRANCH_RE.match(branch)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    head: str
    label: str
    port: int  # 0 means no port assigned (should be cleaned up)


class ManagerState:
    def __init__(self, repo: Path, python: str) -> None:
        self.repo = repo.resolve()
        self.python = python
        self.processes: dict[str, subprocess.Popen] = {}
        self.log_dir = self.repo / ".workspace" / "flask-manager" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def worktrees(self) -> list[Worktree]:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.repo,
            text=True,
        )
        entries: list[dict[str, str]] = []
        cur: dict[str, str] = {}
        for line in out.splitlines():
            if not line:
                if cur:
                    entries.append(cur)
                    cur = {}
                continue
            key, _, value = line.partition(" ")
            cur[key] = value
        if cur:
            entries.append(cur)

        result: list[Worktree] = []
        for entry in entries:
            path = Path(entry.get("worktree", "")).resolve()
            if not path:
                continue
            branch_ref = entry.get("branch", "")
            branch = branch_ref.removeprefix("refs/heads/") if branch_ref else "(detached)"
            head = entry.get("HEAD", "")[:8]

            if branch == "master":
                port = MASTER_PORT
            elif branch == "feat":
                port = FEAT_PORT
            else:
                issue_num = _extract_issue_number(branch)
                if issue_num is not None:
                    port = MASTER_PORT + issue_num
                else:
                    port = 0  # no port — should be cleaned up

            result.append(Worktree(
                path=path, branch=branch, head=head,
                label=branch, port=port,
            ))
        return sorted(result, key=lambda wt: (
            -1 if wt.port == 0 else wt.port, wt.label
        ))  # no-port worktrees at bottom

    def key(self, path: Path) -> str:
        return str(path.resolve())

    def is_running(self, path: Path) -> bool:
        proc = self.processes.get(self.key(path))
        if not proc:
            return False
        if proc.poll() is not None:
            self.processes.pop(self.key(path), None)
            return False
        return True

    def start(self, path: Path, port: int) -> str:
        path = path.resolve()
        if self.is_running(path):
            return "already running"
        if not (path / "start_server.py").exists():
            raise RuntimeError(f"missing start_server.py in {path}")
        if port == 0:
            raise RuntimeError(f"worktree has no assigned port (branch name lacks issue number)")
        if port_in_use(port):
            raise RuntimeError(f"port {port} is already in use")

        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env = os.environ.copy()
        env["FLASK_DEBUG"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        # Worktrees derive DATA_DIR from __file__'s parent, which lands inside
        # .workspace/... instead of the real data directory.  Point FT_DATA_DIR
        # at the repo-level data dir (same one the master/feat worktrees use).
        env.setdefault("FT_DATA_DIR", str(self.repo.parent / "data"))
        proc = subprocess.Popen(
            [self.python, "start_server.py", "--port", str(port)],
            cwd=path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[self.key(path)] = proc
        return f"started pid {proc.pid}"

    def stop(self, path: Path) -> str:
        path = path.resolve()
        proc = self.processes.get(self.key(path))
        if not proc or proc.poll() is not None:
            self.processes.pop(self.key(path), None)
            return "not running"
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        finally:
            self.processes.pop(self.key(path), None)
        return "stopped"

    def stop_all(self) -> None:
        for key in list(self.processes):
            proc = self.processes.get(key)
            if proc and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        self.processes.clear()


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value) or "worktree"


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def page(state: ManagerState, message: str = "") -> bytes:
    rows = []
    for wt in state.worktrees():
        if wt.port == 0:
            # No issue number — show warning, no Start/Stop actions
            rows.append(
                f"""
            <tr class="orphan">
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(str(wt.path))}</code></td>
              <td><span class="muted">—</span></td>
              <td><span class="pill orphan-pill">no-issue</span></td>
              <td><span class="muted">⚠️ 建议清理：分支名不含 issue 编号</span></td>
            </tr>
            """
            )
            continue
        running = state.is_running(wt.path)
        occupied = port_in_use(wt.port) and not running
        status = "running" if running else ("occupied" if occupied else "stopped")
        start_disabled = "disabled" if running or occupied else ""
        stop_disabled = "" if running else "disabled"
        open_disabled = "" if running or occupied else "disabled"
        rows.append(
            f"""
            <tr>
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(str(wt.path))}</code></td>
              <td><a href="http://localhost:{wt.port}/" target="_blank">{wt.port}</a></td>
              <td><span class="pill {status}">{status}</span></td>
              <td>
                <form method="post" action="/start"><input type="hidden" name="path" value="{html.escape(str(wt.path))}"><input type="hidden" name="port" value="{wt.port}"><button {start_disabled}>Start</button></form>
                <form method="post" action="/stop"><input type="hidden" name="path" value="{html.escape(str(wt.path))}"><button {stop_disabled}>Stop</button></form>
                <a class="button {open_disabled}" href="http://localhost:{wt.port}/" target="_blank">Open</a>
              </td>
            </tr>
            """
        )
    msg = f"<div class='message'>{html.escape(message)}</div>" if message else ""
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FactorTester Worktree Flask Manager</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f9fafb; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
    code {{ font-size: 12px; color: #374151; }}
    form {{ display: inline; }}
    button, .button {{ border: 1px solid #cbd5e1; background: #fff; color: #111827; padding: 4px 9px; border-radius: 6px; text-decoration: none; font-size: 13px; cursor: pointer; margin-right: 4px; }}
    button:disabled, .disabled {{ opacity: .45; pointer-events: none; cursor: default; }}
    .muted {{ color: #6b7280; font-size: 12px; margin-top: 2px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
    .running {{ background: #dcfce7; color: #166534; }}
    .stopped {{ background: #f3f4f6; color: #374151; }}
    .occupied {{ background: #fef3c7; color: #92400e; }}
    .orphan {{ background: #fef2f2; }}
    .orphan-pill {{ background: #fee2e2; color: #991b1b; }}
    .message {{ padding: 8px 10px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; margin-bottom: 12px; }}
  </style>
</head>
<body>
  <h1>FactorTester Worktree Flask Manager</h1>
  <p class="muted">Use Start/Stop for ordinary parallel servers. For VS Code breakpoints, launch the matching <code>Flask Debug: ...</code> configuration on the same worktree/port while that port is stopped here.</p>
  {msg}
  <table>
    <thead><tr><th>Worktree</th><th>Path</th><th>Port</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    state: ManagerState

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/worktrees":
            data = [
                {
                    "label": wt.label,
                    "branch": wt.branch,
                    "path": str(wt.path),
                    "port": wt.port,
                    "running": self.state.is_running(wt.path),
                    "port_in_use": port_in_use(wt.port),
                }
                for wt in self.state.worktrees()
            ]
            json_response(self, {"worktrees": data})
            return
        if parsed.path != "/":
            self.send_error(404)
            return
        message = parse_qs(parsed.query).get("message", [""])[0]
        body = page(self.state, message)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        path = Path(params.get("path", [""])[0])
        try:
            if self.path == "/start":
                port = int(params.get("port", ["0"])[0])
                message = self.state.start(path, port)
            elif self.path == "/stop":
                message = self.state.stop(path)
            else:
                self.send_error(404)
                return
        except Exception as exc:
            message = f"error: {exc}"
        self.send_response(303)
        self.send_header("Location", "/?message=" + html.escape(message))
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[manager] " + (fmt % args) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--port", type=int, default=7998)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.state = ManagerState(Path(args.repo), args.python)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Worktree Flask manager running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.state.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
