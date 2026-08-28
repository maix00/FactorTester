"""One Profile's Codex app-server process and protocol policy handshake."""

from __future__ import annotations

from typing import Any, Callable, Mapping
import logging
import threading
import time
import traceback

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_app_server_launch import AgentAppServerLaunch
from server.manager.services.agent_app_server_policy import AgentAppServerPolicy
from server.manager.services.agent_app_server_process import (
    AgentAppServerProcess,
    AgentAppServerProcessError,
)
from server.manager.services.agent_skill_protocol import AgentSkillProtocol
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.services.cc_switch_gateway import CCSwitchGateway


LOGGER = logging.getLogger(__name__)


class AgentAppServerSession:
    """One claimed Profile's app-server process and policy handshake."""

    def __init__(
        self,
        *,
        runtime: AgentSkillRuntime,
        provider: Mapping[str, object],
        codex_binary: str,
        factor_tester_auth: Mapping[str, object] | None = None,
        proxy_url: str = "",
        cc_switch_binary: str = "cc-switch",
        read_only: bool = False,
        event_observer: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.provider = dict(provider)
        self.launch = AgentAppServerLaunch(
            runtime=runtime,
            provider=provider,
            codex_binary=codex_binary,
            factor_tester_auth=factor_tester_auth,
            proxy_url=proxy_url,
        )
        self.protocol = AgentSkillProtocol(runtime)
        self.policy = AgentAppServerPolicy(runtime, self.protocol)
        self.read_only = bool(read_only)
        self.event_observer = event_observer
        self.process: AgentAppServerProcess | None = None
        self.cc_switch = (
            CCSwitchGateway(
                profile_state_root=runtime.state_root / "cc-switch",
                provider=self.provider,
                binary=cc_switch_binary,
                proxy_url=proxy_url,
            )
            if not self.read_only
            and str(self.provider.get("protocol") or "") != "openai_responses"
            else None
        )
        self.ready = False
        self._lock = threading.RLock()

    @staticmethod
    def _error(response: Mapping[str, object], operation: str) -> None:
        if response.get("error") is not None:
            error = response.get("error")
            if isinstance(error, Mapping):
                message = str(error.get("message") or error.get("code") or error)
            else:
                message = str(error)
            raise AgentAppServerError(f"app-server {operation} failed: {message}")

    def start(self) -> None:
        with self._lock:
            if self.ready and self.process is not None and self.process.is_running():
                return
            # Reading a persisted thread does not call the model provider.
            # Avoid making historical access depend on provider network
            # health, while still validating the local executables.
            self.launch.preflight(
                check_provider=not self.read_only,
                require_factor_tester=not self.read_only,
            )
            if self.cc_switch is not None:
                self.launch.provider = self.cc_switch.start()
            self.launch.write_provider_config()
            self.launch.write_factor_tester_config()
            process = AgentAppServerProcess(
                command=self.launch.command(),
                cwd=self.runtime.workspace_root,
                environment=self.launch.environment(),
                event_observer=self.event_observer,
            )
            process.start()
            self.process = process
            stage = "initialize"
            started_at = time.monotonic()
            try:
                response = process.request(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "factor-tester-manager",
                            "title": "FactorTester Manager",
                            "version": "0.1.0",
                        },
                        "capabilities": {},
                    },
                    # A newly isolated CODEX_HOME may need to materialize
                    # Codex-managed system Skills on its first launch.  This
                    # is local work, but it can exceed the ordinary RPC
                    # timeout on a busy Manager host.
                    timeout=60,
                )
                self._error(response, "initialize")
                process.notify("initialized")
                if self.read_only:
                    self.ready = True
                    return
                stage = "skills/list initial"
                skills_response = process.request(
                    "skills/list",
                    self.protocol.skills_list_params(),
                    timeout=20,
                )
                self._error(skills_response, "skills/list")
                discovered = self.protocol.skills_from_response(skills_response)
                for request in self.protocol.policy_requests(
                    discovered,
                    first_request_id=1000,
                ):
                    stage = str(request["method"])
                    policy_response = process.request_with_id(
                        int(request["id"]),
                        str(request["method"]),
                        request.get("params"),
                        timeout=20,
                    )
                    self._error(policy_response, str(request["method"]))
                stage = "skills/list refreshed"
                refreshed = process.request(
                    "skills/list",
                    self.protocol.skills_list_params(),
                    timeout=20,
                )
                self._error(refreshed, "skills/list")
                self.ready = True
            except (
                AgentAppServerProcessError,
                AgentAppServerError,
                OSError,
                ValueError,
            ) as exc:
                status = process.status()
                LOGGER.error(
                    "Profile Agent startup failed stage=%s elapsed=%.3fs "
                    "error=%s returncode=%r stderr=%r",
                    stage,
                    time.monotonic() - started_at,
                    exc,
                    status.get("returncode"),
                    list(status.get("stderr_tail") or [])[-10:],
                )
                process.stop()
                if self.cc_switch is not None:
                    self.cc_switch.stop()
                self.process = None
                self.ready = False
                if isinstance(exc, AgentAppServerError):
                    raise
                raise AgentAppServerError(str(exc)) from exc

    def _prepared_params(
        self,
        method: str,
        params: Mapping[str, object],
    ) -> dict[str, Any]:
        return self.policy.prepare(method, params)

    def request(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self.ready or self.process is None or not self.process.is_running():
                raise AgentAppServerError("Profile Agent is not running")
            try:
                return self.process.request(
                    method,
                    self._prepared_params(method, params or {}),
                    timeout=60 if method == "turn/start" else 20,
                )
            except AgentAppServerProcessError as exc:
                raise AgentAppServerError(str(exc)) from exc

    def delete_thread(self, thread_id: str) -> dict[str, Any]:
        """Delete a thread only after the supervisor verified its ownership."""
        identifier = str(thread_id or "").strip()
        if not identifier:
            raise AgentAppServerError("thread_id is required")
        with self._lock:
            if not self.ready or self.process is None or not self.process.is_running():
                raise AgentAppServerError("Profile Agent is not running")
            try:
                response = self.process.request(
                    "thread/delete",
                    {"threadId": identifier},
                    timeout=20,
                )
            except AgentAppServerProcessError as exc:
                raise AgentAppServerError(str(exc)) from exc
            self._error(response, "thread/delete")
            return response

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        process = self.process
        return [] if process is None else process.events(after)

    def wait_for_events(self, after: int, timeout: float) -> list[dict[str, Any]]:
        process = self.process
        return [] if process is None else process.wait_for_events(after, timeout)

    def status(self) -> dict[str, Any]:
        process = self.process
        running = process is not None and process.is_running()
        return {
            "ready": self.ready and running,
            **(process.status() if process is not None else {
                "running": False,
                "pid": None,
                "returncode": None,
                "event_sequence": 0,
                "stderr_tail": [],
            }),
        }

    def stop(self) -> None:
        with self._lock:
            if self.process is not None:
                LOGGER.warning(
                    "Profile Agent session stop requested profile_workspace=%s "
                    "caller=%s",
                    self.runtime.workspace_root.name,
                    " | ".join(
                        line.strip()
                        for line in traceback.format_stack(limit=7)[:-1]
                    ),
                )
                self.process.stop()
            if self.cc_switch is not None:
                self.cc_switch.stop()
            self.launch.cleanup_factor_tester_config()
            self.process = None
            self.ready = False
