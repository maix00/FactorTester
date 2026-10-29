"""One Profile's Codex app-server process and protocol policy handshake."""

from __future__ import annotations

from typing import Any, Callable, Mapping
import logging
import threading
import time

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
        self.protocol = AgentSkillProtocol(runtime, sandboxed=True)
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
        self._starting = False
        self._stop_requested = threading.Event()

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
            if self._starting:
                raise AgentAppServerError(
                    "Profile Agent startup is already in progress",
                    code="start_in_progress",
                )
            if self._stop_requested.is_set():
                raise AgentAppServerError(
                    "Profile Agent startup was cancelled", code="start_cancelled",
                )
            self._starting = True
        process: AgentAppServerProcess | None = None
        stage = "preflight"
        started_at = time.monotonic()
        try:
            # Do not hold the session lock over provider checks or the app-server
            # handshake. stop() can then terminate a process whose startup is
            # waiting on a slow provider or first-run initialization.
            self.launch.preflight(
                check_provider=not self.read_only,
                require_factor_tester=not self.read_only,
            )
            self._ensure_start_active()
            if self.cc_switch is not None:
                self.launch.provider = self.cc_switch.start()
            self._ensure_start_active()
            self.launch.write_provider_config()
            self.launch.write_factor_tester_config()
            process = AgentAppServerProcess(
                command=self.launch.command(),
                cwd=self.runtime.workspace_root,
                environment=self.launch.environment(),
                event_observer=self.event_observer,
            )
            process.start()
            with self._lock:
                self.process = process
            self._ensure_start_active()
            stage = "initialize"
            response = process.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "traderesearch-manager",
                        "title": "TradeResearch Manager",
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
            if not self.read_only:
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
                    self._ensure_start_active()
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
            self._ensure_start_active()
            with self._lock:
                if self.process is not process or not process.is_running():
                    raise AgentAppServerError(
                        "Profile Agent process exited during startup",
                    )
                self.ready = True
        except (
            AgentAppServerProcessError,
            AgentAppServerError,
            OSError,
            ValueError,
        ) as exc:
            status = process.status() if process is not None else {}
            LOGGER.error(
                "Profile Agent startup failed stage=%s elapsed=%.3fs "
                "error=%s returncode=%r stderr=%r",
                stage,
                time.monotonic() - started_at,
                exc,
                status.get("returncode"),
                list(status.get("stderr_tail") or [])[-10:],
            )
            if process is not None:
                process.stop()
            if self.cc_switch is not None:
                self.cc_switch.stop()
            with self._lock:
                if self.process is process:
                    self.process = None
                self.ready = False
            if self._stop_requested.is_set():
                raise AgentAppServerError(
                    "Profile Agent startup was cancelled", code="start_cancelled",
                ) from exc
            if isinstance(exc, AgentAppServerError):
                raise
            raise AgentAppServerError(str(exc)) from exc
        finally:
            with self._lock:
                self._starting = False

    def _ensure_start_active(self) -> None:
        if self._stop_requested.is_set():
            raise AgentAppServerError(
                "Profile Agent startup was cancelled", code="start_cancelled",
            )

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
            process = self.process
            prepared = self._prepared_params(method, params or {})
        # JSON-RPC may wait for a full model turn. Keep the session lock only
        # for the short state snapshot so stop() can terminate the child
        # immediately instead of waiting behind the model request timeout.
        try:
            response = process.request(
                method,
                prepared,
                timeout=60 if method == "turn/start" else 20,
            )
        except AgentAppServerProcessError as exc:
            raise AgentAppServerError(str(exc)) from exc
        self._error(response, method)
        return response

    def delete_thread(self, thread_id: str) -> dict[str, Any]:
        """Delete a thread only after the supervisor verified its ownership."""
        identifier = str(thread_id or "").strip()
        if not identifier:
            raise AgentAppServerError("thread_id is required")
        with self._lock:
            if not self.ready or self.process is None or not self.process.is_running():
                raise AgentAppServerError("Profile Agent is not running")
            process = self.process
        try:
            response = process.request(
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
        self._stop_requested.set()
        with self._lock:
            process = self.process
            self.process = None
            self.ready = False
        if process is not None:
            process.stop()
        with self._lock:
            if self.cc_switch is not None:
                self.cc_switch.stop()
            self.launch.cleanup_factor_tester_config()
