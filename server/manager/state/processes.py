"""Lifecycle operations for FactorTester, artifact, and Vibe services."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from server.manager.config import VIBE_TRADING_PORT
from server.manager.storage.control_db import CONTROL_DATABASE_ENV
from server.manager.state.models import ServiceBundle
from server.manager.system import safe_name


def job_daemon_socket_path(path: Path, deployment_id: str) -> Path:
    """Return an ephemeral socket path on the Manager's native filesystem."""
    runtime_root = str(
        os.environ.get("FACTORTESTER_JOB_DAEMON_RUNTIME_DIR") or ""
    ).strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve() / f"{deployment_id}.sock"
    return path / ".workspace" / "runtime" / f"{deployment_id}.sock"


class ProcessStateMixin:
    """Start, stop, and restart services after route selection is complete."""

    def _inject_control_database_env(self, env: dict[str, str]) -> None:
        """Project this node's persisted control-plane setting into a child."""
        configured = self.control_database_settings.effective_url()
        if configured:
            env[CONTROL_DATABASE_ENV] = configured
        else:
            env.pop(CONTROL_DATABASE_ENV, None)

    def start_vibe(self) -> str:
        if self.vibe_running():
            return "Vibe-Trading already running"
        if self._port_is_in_use(VIBE_TRADING_PORT):
            raise RuntimeError(
                f"Vibe-Trading port {VIBE_TRADING_PORT} is already in use"
            )
        executable = (
            self.vibe_trading_root / ".conda" / "bin" / "vibe-trading"
        )
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
            cwd=self.vibe_trading_root,
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
        socket_path = job_daemon_socket_path(path, deployment_id)
        env = os.environ.copy()
        python_path = [
            item
            for item in env.get("PYTHONPATH", "").split(os.pathsep)
            if item
        ]
        source_revision = str(env.get("GTHT_SOURCE_REVISION") or "").strip()
        if not source_revision:
            source_revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=path, text=True
            ).strip()
        service_debug = str(
            env.get("FACTORTESTER_SERVICE_DEBUG", "1")
        ).strip().lower() in {"1", "true", "yes", "on"}
        env.update({
            "FLASK_DEBUG": "1" if service_debug else "0",
            "FACTORTESTER_WERKZEUG_RELOADER": "0",
            # ADR 056 makes 7998 the only cross-host control-plane entry.
            # Service ports stay reachable from this Manager and from the
            # local browser, but must not become parallel public listeners.
            "FACTORTESTER_SERVICE_HOST": "127.0.0.1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(python_path),
            "GTHT_DEPLOYMENT_ID": deployment_id,
            "GTHT_JOB_DAEMON_SOCKET": str(socket_path),
            "GTHT_SOURCE_REVISION": source_revision,
            "GTHT_JOB_ARTIFACT_ROOT": str(self.data_root / "job-results"),
            "FACTORTESTER_SERVER_ID": self.server_id,
            "FACTORTESTER_SERVER_ROLE": self.server_role,
        })
        self._inject_control_database_env(env)
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
            self.service_intents.mark_running(path, port)
            return "already running"
        existing = self.processes.get(self.key(path))
        if existing is not None and existing.daemon.poll() is None:
            message = self.restart_api(path, port)
            self.service_intents.mark_running(path, port)
            return message
        if existing is not None:
            self.processes.pop(self.key(path), None)
        if not (path / "start_server.py").exists():
            raise RuntimeError(f"missing start_server.py in {path}")
        if port == 0:
            raise RuntimeError(f"worktree has no assigned port (branch name lacks issue number)")
        if self._port_is_in_use(port):
            raise RuntimeError(f"port {port} is already in use")

        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, deployment_id, socket_path = self._service_env(path, port)
        if self.fixed_port and port == self.fixed_port and self.fixed_daemon_socket:
            socket_path = Path(self.fixed_daemon_socket).expanduser().resolve()
            env["GTHT_JOB_DAEMON_SOCKET"] = str(socket_path)
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
        self.service_intents.mark_running(path, port)
        return f"started api pid {api.pid}, daemon pid {daemon.pid}"

    def restore_desired_services(self) -> list[dict[str, object]]:
        """Reconcile persisted intent with current, executable worktrees."""
        intents = self.service_intents.services()
        if not intents:
            return []
        worktrees = {
            self.key(item.path): item
            for item in self.worktrees()
            if item.port
        }
        restored: list[dict[str, object]] = []
        for intent in intents:
            path = Path(str(intent["path"])).resolve()
            port = int(intent["port"])
            worktree = worktrees.get(self.key(path))
            if worktree is None or worktree.port != port:
                self.service_intents.mark_stopped(path)
                restored.append({
                    "path": str(path),
                    "port": port,
                    "status": "removed",
                })
                continue
            try:
                message = self.start(path, port)
            except (OSError, RuntimeError, ValueError) as exc:
                restored.append({
                    "path": str(path),
                    "port": port,
                    "status": "error",
                    "error": str(exc),
                })
                continue
            restored.append({
                "path": str(path),
                "port": port,
                "status": (
                    "running" if message == "already running" else "started"
                ),
            })
        return restored

    def restart_api(self, path: Path, port: int) -> str:
        path = path.resolve()
        bundle = self._bundle_for_path(path)
        if bundle is None or bundle.daemon.poll() is not None:
            raise RuntimeError("research daemon is not running")
        if bundle.api.poll() is None:
            self._terminate(bundle.api)
        log_file = self.log_dir / f"{safe_name(path.name)}-{port}.log"
        log = log_file.open("ab", buffering=0)
        env, _, _ = self._service_env(path, port)
        if self.fixed_port and port == self.fixed_port and self.fixed_daemon_socket:
            env["GTHT_JOB_DAEMON_SOCKET"] = str(
                Path(self.fixed_daemon_socket).expanduser().resolve()
            )
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
        bundle = self._bundle_for_path(path)
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

    def stop(
        self,
        path: Path,
        *,
        force: bool = False,
        preserve_intent: bool = False,
    ) -> str:
        path = path.resolve()
        bundle = self._bundle_for_path(path)
        if not bundle:
            self.processes.pop(self.key(path), None)
            if not preserve_intent:
                self.service_intents.mark_stopped(path)
            return "not running"
        if not force and bundle.daemon.poll() is None:
            health = self._daemon_request(bundle, "health")
            active = int(health.get("active_planners") or 0) + int(health.get("active_executors") or 0)
            if active:
                raise RuntimeError("active research jobs block Stop; use Restart Bundle or Force Stop")
        self._terminate(bundle.api)
        self._terminate(bundle.daemon)
        self.processes.pop(self.key(path), None)
        if not preserve_intent:
            self.service_intents.mark_stopped(path)
        return "stopped"

    def stop_all(self) -> None:
        agent_supervisor = getattr(self, "agent_app_server", None)
        if agent_supervisor is not None:
            agent_supervisor.stop_all()
        self.stop_federation_announcer()
        self.stop_federation_sync()
        for key in list(self.processes):
            bundle = self.processes.get(key)
            if bundle:
                self.stop(Path(key), force=True, preserve_intent=True)
        self.processes.clear()
        self.stop_data_plane()
        self.stop_vibe()
        self.mihomo.close()
