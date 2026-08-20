"""Profile-isolated gateway backed by the pinned CC Switch CLI service layer."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from server.manager.services.agent_app_server_errors import AgentAppServerError


CC_SWITCH_PROTOCOLS = {
    "openai_responses": "responses",
    "openai_chat": "chat",
    "anthropic_messages": "anthropic",
}


@dataclass(frozen=True)
class CCSwitchGatewayPlan:
    """Commands and private files used by one isolated CC Switch process."""

    environment: dict[str, str]
    provider_config_path: Path
    setup_command: list[str]
    switch_command: list[str]
    config_command: list[str]
    serve_command: list[str]
    proxy_url: str
    child_provider: dict[str, object]


class CCSwitchGateway:
    """Run CC Switch on loopback for exactly one Profile Agent session.

    FactorTester deliberately invokes CC Switch instead of copying its request
    and streaming transforms.  Each session gets a private config directory so
    providers, credentials, telemetry, and failover state cannot cross Profile
    boundaries.
    """

    def __init__(
        self,
        *,
        profile_state_root: str | Path,
        provider: Mapping[str, object],
        binary: str = "cc-switch",
    ) -> None:
        self.profile_state_root = Path(profile_state_root).expanduser().resolve()
        self.provider = dict(provider)
        self.binary = str(binary or "cc-switch").strip() or "cc-switch"
        self._session_root: Path | None = None
        self._process: subprocess.Popen[str] | None = None
        self._plan: CCSwitchGatewayPlan | None = None

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _private_session_root(self) -> Path:
        self.profile_state_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.profile_state_root, 0o700)
        except OSError:
            pass
        root = Path(tempfile.mkdtemp(prefix="cc-switch-", dir=self.profile_state_root))
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        self._session_root = root
        return root

    def plan(self, *, port: int | None = None) -> CCSwitchGatewayPlan:
        protocol = str(self.provider.get("protocol") or "").strip()
        api_format = CC_SWITCH_PROTOCOLS.get(protocol)
        if not api_format:
            raise AgentAppServerError(
                "CC Switch does not support this Codex provider protocol"
            )
        base_url = str(self.provider.get("base_url") or "").strip().rstrip("/")
        model = str(self.provider.get("default_model") or "").strip()
        secret = str(self.provider.get("secret") or "")
        if not base_url or not model or not secret:
            raise AgentAppServerError("Agent provider is incomplete")

        root = self._private_session_root()
        config_root = root / "state"
        config_root.mkdir(mode=0o700)
        provider_config_path = root / "provider.json"
        provider_key = "factortester-profile-provider"
        provider_toml = "\n".join([
            f'model = {json.dumps(model)}',
            f'base_url = {json.dumps(base_url)}',
        ])
        provider_config_path.write_text(
            json.dumps(
                {
                    "auth": {"OPENAI_API_KEY": secret},
                    "config": provider_toml,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.chmod(provider_config_path, 0o600)

        listen_port = int(port or self._free_loopback_port())
        if not 1 <= listen_port <= 65535:
            raise AgentAppServerError("CC Switch loopback port is invalid")
        executable = self.binary
        environment = dict(os.environ)
        environment["CC_SWITCH_CONFIG_DIR"] = str(config_root)
        local_token = secrets.token_urlsafe(32)
        plan = CCSwitchGatewayPlan(
            environment=environment,
            provider_config_path=provider_config_path,
            setup_command=[
                executable,
                "--app", "codex",
                "provider", "add",
                "--name", "FactorTester Profile provider",
                "--id", provider_key,
                "--config-file", str(provider_config_path),
                "--api-format", api_format,
            ],
            switch_command=[
                executable, "--app", "codex", "provider", "switch", provider_key,
            ],
            config_command=[
                executable,
                "--app", "codex",
                "proxy", "config",
                "--listen-address", "127.0.0.1",
                "--listen-port", str(listen_port),
            ],
            serve_command=[
                executable,
                "--app", "codex",
                "proxy", "serve",
                "--takeover", "codex",
                "--listen-address", "127.0.0.1",
                "--listen-port", str(listen_port),
            ],
            proxy_url=f"http://127.0.0.1:{listen_port}/v1",
            child_provider={
                **self.provider,
                "protocol": "openai_responses",
                "base_url": f"http://127.0.0.1:{listen_port}/v1",
                "secret": local_token,
            },
        )
        self._plan = plan
        return plan

    @staticmethod
    def _run_setup(command: list[str], environment: Mapping[str, str]) -> None:
        try:
            result = subprocess.run(
                command,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AgentAppServerError("CC Switch setup failed") from exc
        if result.returncode != 0:
            raise AgentAppServerError("CC Switch setup failed")

    @staticmethod
    def _is_ready(proxy_url: str) -> bool:
        host_port = proxy_url.removeprefix("http://").split("/", 1)[0]
        host, port = host_port.rsplit(":", 1)
        try:
            with socket.create_connection((host, int(port)), timeout=0.2):
                return True
        except OSError:
            return False

    def start(self) -> dict[str, object]:
        if self._process is not None and self._process.poll() is None and self._plan:
            return dict(self._plan.child_provider)
        if not shutil.which(self.binary):
            raise AgentAppServerError("CC Switch executable is unavailable")
        plan = self.plan()
        try:
            for command in (
                plan.setup_command,
                plan.switch_command,
                plan.config_command,
            ):
                self._run_setup(command, plan.environment)
            plan.provider_config_path.unlink(missing_ok=True)
            self._process = subprocess.Popen(
                plan.serve_command,
                env=plan.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    break
                if self._is_ready(plan.proxy_url):
                    return dict(plan.child_provider)
                time.sleep(0.05)
            raise AgentAppServerError("CC Switch proxy did not become ready")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        root = self._session_root
        self._session_root = None
        self._plan = None
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)


__all__ = ["CCSwitchGateway", "CCSwitchGatewayPlan", "CC_SWITCH_PROTOCOLS"]
