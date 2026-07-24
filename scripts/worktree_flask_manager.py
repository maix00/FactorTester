#!/usr/bin/env python3
"""Run a small local UI for starting Flask from multiple git worktrees."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse



MAIN_PORT = 8000
FEAT_PORT = 7999
VIBE_TRADING_PORT = 7899
VIBE_TRADING_ROOT = Path(
    os.environ.get(
        "VIBE_TRADING_ROOT",
        "/Users/maxdeux/Documents/Vibe-Trading-Integration",
    )
).expanduser()

# Matches branches named fix/issue-<N>-<slug> or fix/issue-<N>
_ISSUE_BRANCH_RE = re.compile(r'^fix/issue-(\d+)(?:-.*)?$')


def _extract_issue_number(branch: str) -> int | None:
    m = _ISSUE_BRANCH_RE.match(branch)
    return int(m.group(1)) if m else None


def _write_owner_only_once(path: Path, value: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, value.encode("ascii"))
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    head: str
    label: str
    port: int  # 0 means no port assigned (should be cleaned up)


@dataclass
class ServiceBundle:
    api: subprocess.Popen
    daemon: subprocess.Popen
    socket_path: Path
    deployment_id: str


class ManagerState:
    def __init__(self, repo: Path, python: str) -> None:
        self.repo = repo.resolve()
        self.python = python
        self.processes: dict[str, ServiceBundle] = {}
        self.vibe_process: subprocess.Popen | None = None
        self.log_dir = self.repo / ".workspace" / "flask-manager" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.secret_path = self.log_dir.parent / "flask-secret.key"
        self.capability_path = self.log_dir.parent / "manager-capability.key"

    def submit_action(self, operation, label: str) -> None:
        """Run one already-authorized operation after its HTTP receipt."""
        def run() -> None:
            try:
                operation()
            except Exception as exc:
                sys.stderr.write(f"[manager] async action {label} failed: {exc}\n")

        threading.Thread(
            target=run,
            name=f"manager-action-{hashlib.sha256(label.encode()).hexdigest()[:8]}",
            daemon=True,
        ).start()

    def _flask_secret(self) -> str:
        if not self.secret_path.exists():
            self.secret_path.write_text(secrets.token_hex(32), encoding="ascii")
        self.secret_path.chmod(0o600)
        value = self.secret_path.read_text(encoding="ascii").strip()
        if not value:
            raise RuntimeError("Flask session secret is empty")
        return value

    def capability_token(self) -> str:
        if not self.capability_path.exists():
            _write_owner_only_once(self.capability_path, secrets.token_hex(32))
        self.capability_path.chmod(0o600)
        value = self.capability_path.read_text(encoding="ascii").strip()
        if not value:
            raise RuntimeError("manager capability token is empty")
        return value

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

            if branch in {"main", "master"}:
                port = MAIN_PORT
            elif branch == "feat":
                port = FEAT_PORT
            else:
                issue_num = _extract_issue_number(branch)
                if issue_num is not None:
                    port = MAIN_PORT + issue_num
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

    def instance_id(self, worktree: Worktree) -> str:
        digest = hmac.new(
            self.capability_token().encode("ascii"),
            self.key(worktree.path).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24]
        return f"worktree-{digest}"

    def worktree_for_instance(self, instance_id: str) -> Worktree | None:
        return next(
            (
                item
                for item in self.worktrees()
                if self.instance_id(item) == str(instance_id)
            ),
            None,
        )

    def is_running(self, path: Path) -> bool:
        bundle = self.processes.get(self.key(path))
        if not bundle:
            return False
        if bundle.api.poll() is not None:
            return False
        return True

    def daemon_running(self, path: Path) -> bool:
        bundle = self.processes.get(self.key(path))
        return bool(bundle and bundle.daemon.poll() is None)

    def vibe_running(self) -> bool:
        return bool(
            self.vibe_process is not None
            and self.vibe_process.poll() is None
        )

    def start_vibe(self) -> str:
        if self.vibe_running():
            return "Vibe-Trading already running"
        if port_in_use(VIBE_TRADING_PORT):
            raise RuntimeError(
                f"Vibe-Trading port {VIBE_TRADING_PORT} is already in use"
            )
        executable = VIBE_TRADING_ROOT / ".conda" / "bin" / "vibe-trading"
        if not executable.is_file():
            raise RuntimeError(f"missing Vibe-Trading executable: {executable}")
        log_file = self.log_dir / f"vibe-trading-{VIBE_TRADING_PORT}.log"
        log = log_file.open("ab", buffering=0)
        self.vibe_process = subprocess.Popen(
            [
                str(executable),
                "serve",
                "--host", "127.0.0.1",
                "--port", str(VIBE_TRADING_PORT),
            ],
            cwd=VIBE_TRADING_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return f"started Vibe-Trading pid {self.vibe_process.pid}"

    def stop_vibe(self) -> str:
        process = self.vibe_process
        if process is None or process.poll() is not None:
            self.vibe_process = None
            return "Vibe-Trading not running"
        self._terminate(process)
        self.vibe_process = None
        return "stopped Vibe-Trading"

    def _service_env(self, path: Path, port: int) -> tuple[dict[str, str], str, Path]:
        deployment_id = f"{safe_name(path.name)}-{port}"
        socket_path = path / ".workspace" / "runtime" / f"{deployment_id}.sock"
        env = os.environ.copy()
        harness_root = str(
            (path / "tools" / "cli" / "agent-harness").resolve()
        )
        python_path = [
            item
            for item in env.get("PYTHONPATH", "").split(os.pathsep)
            if item
        ]
        if harness_root not in python_path:
            python_path.insert(0, harness_root)
        env.update({
            "FLASK_DEBUG": "1",
            "FACTORTESTER_WERKZEUG_RELOADER": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(python_path),
            "GTHT_DEPLOYMENT_ID": deployment_id,
            "GTHT_JOB_DAEMON_SOCKET": str(socket_path),
            "GTHT_SOURCE_REVISION": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=path, text=True
            ).strip(),
            "GTHT_JOB_ARTIFACT_ROOT": str(path / ".workspace" / "job-results"),
            "FLASK_SECRET_KEY": self._flask_secret(),
        })
        return env, deployment_id, socket_path

    def _start_api(self, path: Path, port: int, env: dict[str, str], log) -> subprocess.Popen:
        api_env = env.copy()
        api_env["GTHT_MANAGER_CAPABILITY_TOKEN"] = self.capability_token()
        return subprocess.Popen(
            [self.python, "start_server.py", "--port", str(port)],
            cwd=path,
            env=api_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def start(self, path: Path, port: int) -> str:
        path = path.resolve()
        if self.is_running(path):
            return "already running"
        existing = self.processes.get(self.key(path))
        if existing is not None and existing.daemon.poll() is None:
            return self.restart_api(path, port)
        if existing is not None:
            self.processes.pop(self.key(path), None)
        if not (path / "start_server.py").exists():
            raise RuntimeError(f"missing start_server.py in {path}")
        if port == 0:
            raise RuntimeError(f"worktree has no assigned port (branch name lacks issue number)")
        if port_in_use(port):
            raise RuntimeError(f"port {port} is already in use")

        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, deployment_id, socket_path = self._service_env(path, port)
        daemon = subprocess.Popen(
            [
                self.python,
                "scripts/research_job_daemon.py",
                "--deployment-id", deployment_id,
                "--socket", str(socket_path),
            ],
            cwd=path,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        api = self._start_api(path, port, env, log)
        self.processes[self.key(path)] = ServiceBundle(
            api=api,
            daemon=daemon,
            socket_path=socket_path,
            deployment_id=deployment_id,
        )
        return f"started api pid {api.pid}, daemon pid {daemon.pid}"

    def restart_api(self, path: Path, port: int) -> str:
        path = path.resolve()
        bundle = self.processes.get(self.key(path))
        if bundle is None or bundle.daemon.poll() is not None:
            raise RuntimeError("research daemon is not running")
        if bundle.api.poll() is None:
            self._terminate(bundle.api)
        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, _, _ = self._service_env(path, port)
        bundle.api = self._start_api(path, port, env, log)
        return f"restarted api pid {bundle.api.pid}; daemon pid {bundle.daemon.pid} preserved"

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)

    @staticmethod
    def _normalized_socket_path(path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if len(str(resolved).encode()) <= 96:
            return resolved
        digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
        return Path(tempfile.gettempdir()) / "factortester-jobs" / f"{digest}.sock"

    def _daemon_request(self, bundle: ServiceBundle, action: str) -> dict:
        address = self._normalized_socket_path(bundle.socket_path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(address))
            sock.sendall(json.dumps({"action": action}).encode() + b"\n")
            raw = sock.makefile("rb").readline()
        payload = json.loads(raw.decode())
        if not payload.get("success"):
            raise RuntimeError(payload.get("error") or "job daemon request failed")
        return payload

    def restart_bundle(self, path: Path, port: int, *, timeout: float = 120.0) -> str:
        path = path.resolve()
        bundle = self.processes.get(self.key(path))
        if bundle is None:
            return self.start(path, port)
        if bundle.daemon.poll() is not None:
            self._terminate(bundle.api)
            self._terminate(bundle.daemon)
            self.processes.pop(self.key(path), None)
            return self.start(path, port)
        health = self._daemon_request(bundle, "drain")
        if health.get("paused_jobs"):
            self._daemon_request(bundle, "resume")
            raise RuntimeError("paused step jobs block bundle restart; cancel them or use Force Stop")
        deadline = time.monotonic() + max(1.0, float(timeout))
        while int(health.get("active_planners") or 0) or int(health.get("active_executors") or 0):
            if time.monotonic() >= deadline:
                self._daemon_request(bundle, "resume")
                raise TimeoutError("timed out draining research workers")
            time.sleep(0.2)
            health = self._daemon_request(bundle, "health")
            if health.get("paused_jobs"):
                self._daemon_request(bundle, "resume")
                raise RuntimeError("job paused during drain; cancel it or use Force Stop")
        self._terminate(bundle.api)
        self._terminate(bundle.daemon)
        self.processes.pop(self.key(path), None)
        return self.start(path, port)

    def stop(self, path: Path, *, force: bool = False) -> str:
        path = path.resolve()
        bundle = self.processes.get(self.key(path))
        if not bundle:
            self.processes.pop(self.key(path), None)
            return "not running"
        if not force and bundle.daemon.poll() is None:
            health = self._daemon_request(bundle, "health")
            active = int(health.get("active_planners") or 0) + int(health.get("active_executors") or 0)
            if active:
                raise RuntimeError("active research jobs block Stop; use Restart Bundle or Force Stop")
        self._terminate(bundle.api)
        self._terminate(bundle.daemon)
        self.processes.pop(self.key(path), None)
        return "stopped"

    def stop_all(self) -> None:
        for key in list(self.processes):
            bundle = self.processes.get(key)
            if bundle:
                self.stop(Path(key), force=True)
        self.processes.clear()
        self.stop_vibe()


def _lan_ip() -> str:
    """Return LAN IP or 'localhost' if unavailable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.0)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


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
    lan = _lan_ip()
    rows = []
    for wt in state.worktrees():
        instance_id = state.instance_id(wt)
        if wt.port == 0:
            # No issue number — show warning, no Start/Stop actions
            rows.append(
                f"""
            <tr class="orphan">
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><span class="muted">—</span></td>
              <td><span class="pill orphan-pill">no-issue</span></td>
              <td><span class="muted">⚠️ 建议清理：分支名不含 issue 编号</span></td>
            </tr>
            """
            )
            continue
        running = state.is_running(wt.path)
        occupied = port_in_use(wt.port) and not running
        daemon_running = state.daemon_running(wt.path)
        status = "running" if running and daemon_running else ("degraded" if running else ("occupied" if occupied else "stopped"))
        start_disabled = "disabled" if running or occupied else ""
        stop_disabled = "" if running or daemon_running else "disabled"
        open_disabled = "" if running or occupied else "disabled"
        rows.append(
            f"""
            <tr>
              <td><strong>{html.escape(wt.label)}</strong><div class="muted">{html.escape(wt.branch)} · {html.escape(wt.head)}</div></td>
              <td><code>{html.escape(instance_id)}</code></td>
              <td><a href="http://localhost:{wt.port}/" target="_blank" title="localhost">{wt.port}</a> <span class="muted">|</span> <a href="http://{lan}:{wt.port}/" target="_blank" title="LAN ({lan})" class="lan-link">🌐</a></td>
              <td><span class="pill {status}">{status}</span></td>
              <td>
                <form method="post" action="/start"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {start_disabled}>Start</button></form>
                <form method="post" action="/stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Stop</button></form>
                <form method="post" action="/restart-api"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart API</button></form>
                <form method="post" action="/restart-bundle"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {'' if daemon_running else 'disabled'}>Restart Bundle</button></form>
                <form method="post" action="/force-stop"><input type="hidden" name="instance_id" value="{html.escape(instance_id)}"><button {stop_disabled}>Force Stop</button></form>
                <a class="button {open_disabled}" href="http://localhost:{wt.port}/" target="_blank">Open</a>
                <a class="button {open_disabled}" href="http://{lan}:{wt.port}/" target="_blank" title="LAN 访问">🌐 Open</a>
              </td>
            </tr>
            """
        )
    msg = f"<div class='message'>{html.escape(message)}</div>" if message else ""
    vibe_running = state.vibe_running()
    vibe_occupied = port_in_use(VIBE_TRADING_PORT) and not vibe_running
    vibe_status = (
        "running" if vibe_running else "occupied" if vibe_occupied else "stopped"
    )
    vibe_start_disabled = "disabled" if vibe_running or vibe_occupied else ""
    vibe_stop_disabled = "" if vibe_running else "disabled"
    vibe_open_disabled = "" if vibe_running or vibe_occupied else "disabled"
    vibe_row = f"""
      <tr>
        <td><strong>Vibe-Trading</strong><div class="muted">research UI + MaxA MCP gateway</div></td>
        <td><code>service-vibe-trading</code></td>
        <td><a href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">{VIBE_TRADING_PORT}</a></td>
        <td><span class="pill {vibe_status}">{vibe_status}</span></td>
        <td>
          <form method="post" action="/vibe/start"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_start_disabled}>Start</button></form>
          <form method="post" action="/vibe/stop"><input type="hidden" name="instance_id" value="service-vibe-trading"><button {vibe_stop_disabled}>Stop</button></form>
          <a class="button {vibe_open_disabled}" href="http://localhost:{VIBE_TRADING_PORT}/" target="_blank">Open</a>
        </td>
      </tr>
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FactorTester Worktree Flask Manager</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ font-size: 22px; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px; text-align: left; vertical-align: top; }}
    th:nth-child(1), td:nth-child(1) {{ width: auto; }}
    th:nth-child(2), td:nth-child(2) {{ width: auto; }}
    th:nth-child(3), td:nth-child(3) {{ width: 85px; }}
    th:nth-child(4), td:nth-child(4) {{ width: 85px; }}
    th:nth-child(5), td:nth-child(5) {{ width: 280px; white-space: nowrap; }}
    th {{ background: #f9fafb; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
    code {{ font-size: 12px; color: #374151; word-break: break-all; }}
    form {{ display: inline; }}
    button, .button {{ border: 1px solid #cbd5e1; background: #fff; color: #111827; padding: 4px 9px; border-radius: 6px; text-decoration: none; font-size: 13px; cursor: pointer; margin-right: 4px; }}
    button:disabled, .disabled {{ opacity: .45; pointer-events: none; cursor: default; }}
    .muted {{ color: #6b7280; font-size: 12px; margin-top: 2px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}
    .running {{ background: #dcfce7; color: #166534; }}
    .stopped {{ background: #f3f4f6; color: #374151; }}
    .occupied {{ background: #fef3c7; color: #92400e; }}
    .degraded {{ background: #fee2e2; color: #991b1b; }}
    .orphan {{ background: #fef2f2; }}
    .orphan-pill {{ background: #fee2e2; color: #991b1b; }}
    .message {{ padding: 8px 10px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; margin-bottom: 12px; }}
    .lan-link {{ text-decoration: none; font-size: 14px; }}
  </style>
</head>
<body>
  <h1>FactorTester Worktree Flask Manager</h1>
  <p class="muted" style="margin-bottom:4px">Use Start/Stop for ordinary parallel servers. For VS Code breakpoints, launch the matching <code>Flask Debug: ...</code> configuration on the same worktree/port while that port is stopped here.</p>
  <p class="muted" style="margin-bottom:12px">🌐 局域网访问本机: <strong>{lan}</strong>（同一热点/网络下的设备使用此 IP + 端口号访问）</p>
  {msg}
  <table>
    <thead><tr><th>Worktree</th><th>Instance</th><th>Port</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>{vibe_row}{''.join(rows)}</tbody>
  </table>
</body>
</html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    state: ManagerState

    def _is_loopback_client(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _is_same_origin_browser_action(self) -> bool:
        if not self._is_loopback_client():
            return False
        origin = self.headers.get("Origin", "").rstrip("/")
        host = self.headers.get("Host", "").strip()
        return bool(origin and host and origin == f"http://{host}")

    def _has_capability(self) -> bool:
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        return (
            scheme.lower() == "bearer"
            and bool(supplied)
            and hmac.compare_digest(supplied, self.state.capability_token())
        )

    def _require_capability(self) -> bool:
        if self._has_capability():
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", "Bearer")
        body = b'{"error":"manager capability required"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/worktrees":
            if not self._require_capability():
                return
            data = [
                {
                    "instance_id": self.state.instance_id(wt),
                    "label": wt.label,
                    "branch": wt.branch,
                    "port": wt.port,
                    "running": self.state.is_running(wt.path),
                    "daemon_running": self.state.daemon_running(wt.path),
                    "port_in_use": port_in_use(wt.port),
                }
                for wt in self.state.worktrees()
            ]
            json_response(self, {
                "worktrees": data,
                "vibe_trading": {
                    "instance_id": "service-vibe-trading",
                    "port": VIBE_TRADING_PORT,
                    "running": self.state.vibe_running(),
                    "port_in_use": port_in_use(VIBE_TRADING_PORT),
                },
            })
            return
        if parsed.path != "/":
            self.send_error(404)
            return
        if not (self._is_loopback_client() or self._require_capability()):
            return
        message = parse_qs(parsed.query).get("message", [""])[0]
        body = page(self.state, message)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        actions = {
            "/vibe/start",
            "/vibe/stop",
            "/start",
            "/stop",
            "/restart-api",
            "/restart-bundle",
            "/force-stop",
        }
        if self.path not in actions:
            self.send_error(404)
            return
        if not (
            self._has_capability()
            or self._is_same_origin_browser_action()
        ):
            self._require_capability()
            return
        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        if set(params) != {"instance_id"} or len(params["instance_id"]) != 1:
            json_response(
                self,
                {"success": False, "error": "instance_id is required and is the only accepted target"},
                400,
            )
            return
        instance_id = str(params["instance_id"][0])
        try:
            operation = self._resolve_operation(instance_id)
        except LookupError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return
        if self.headers.get("Prefer", "").strip().lower() == "respond-async":
            json_response(self, {
                "success": True,
                "submitted": True,
                "instance_id": instance_id,
            }, 202)
            self.state.submit_action(operation, f"{self.path} {instance_id}")
            return
        try:
            message = operation()
        except Exception as exc:
            sys.stderr.write(f"[manager] action {self.path} failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager action failed"},
                409,
            )
            return
        json_response(self, {
            "success": True,
            "instance_id": instance_id,
            "message": message,
        })

    def _resolve_operation(self, instance_id: str):
        if self.path == "/vibe/start":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.start_vibe
        if self.path == "/vibe/stop":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.stop_vibe
        worktree = self.state.worktree_for_instance(instance_id)
        if worktree is None:
            raise LookupError("managed instance not found")
        if self.path == "/start":
            return lambda: self.state.start(worktree.path, worktree.port)
        if self.path == "/stop":
            return lambda: self.state.stop(worktree.path)
        if self.path == "/restart-api":
            return lambda: self.state.restart_api(worktree.path, worktree.port)
        if self.path == "/restart-bundle":
            return lambda: self.state.restart_bundle(worktree.path, worktree.port)
        return lambda: self.state.stop(worktree.path, force=True)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[manager] " + (fmt % args) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7998)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.state = ManagerState(Path(args.repo), args.python)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://localhost:{args.port}/"
    print(f"Worktree Flask manager running at {url}")
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
        if lan_ip and not lan_ip.startswith("127."):
            print(f"  局域网访问: http://{lan_ip}:{args.port}/")
    except Exception:
        pass
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
