"""Profile-scoped Codex app-server configuration and child environment."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_provider_health import (
    AgentProviderHealth,
    AgentProviderHealthError,
)
from server.manager.services.agent_skill_runtime import AgentSkillRuntime


def _toml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _toml_array(values: list[object]) -> str:
    return json.dumps([str(value) for value in values], ensure_ascii=False)


class AgentAppServerLaunch:
    """Build a launch without persisting a provider token."""

    def __init__(
        self,
        *,
        runtime: AgentSkillRuntime,
        provider: Mapping[str, object],
        codex_binary: str,
        factor_tester_cli: str = "",
        proxy_url: str = "",
    ) -> None:
        self.runtime = runtime
        self.provider = dict(provider)
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"
        configured_cli = str(factor_tester_cli or os.environ.get("FACTORTESTER_CLI") or "").strip()
        self.factor_tester_cli = configured_cli or str(
            shutil.which("factortester") or ""
        )
        self.proxy_url = str(proxy_url or "").strip()

    @staticmethod
    def _executable(value: str, label: str) -> str:
        resolved = shutil.which(str(value or "").strip())
        if not resolved:
            raise AgentAppServerError(f"{label} executable is unavailable")
        return resolved

    def preflight(self) -> dict[str, object]:
        """Validate all local and remote prerequisites before spawning Codex."""
        codex = self._executable(self.codex_binary, "Codex")
        factor_tester = self._executable(
            self.factor_tester_cli,
            "FactorTester CLI",
        )
        try:
            provider = (
                AgentProviderHealth.test(
                    self.provider,
                    proxy_url=self.proxy_url,
                )
                if self.proxy_url
                else AgentProviderHealth.test(self.provider)
            )
        except AgentProviderHealthError as exc:
            raise AgentAppServerError(
                f"Agent provider preflight failed: {exc}"
            ) from exc
        return {
            "codex": codex,
            "factor_tester_cli": factor_tester,
            "provider": provider,
        }

    def write_provider_config(self) -> None:
        model = str(self.provider.get("default_model") or "").strip()
        base_url = str(self.provider.get("base_url") or "").strip()
        if not model or not base_url:
            raise AgentAppServerError("Agent provider is incomplete")
        config = "\n".join([
            f"model = {_toml_string(model)}",
            'model_provider = "factortester"',
            'approval_policy = "never"',
            'sandbox_mode = "workspace-write"',
            "sandbox_workspace_write.network_access = true",
            "sandbox_workspace_write.writable_roots = "
            f"{_toml_array([self.runtime.workspace_root])}",
            "",
            "[model_providers.factortester]",
            'name = "FactorTester provider"',
            f"base_url = {_toml_string(base_url)}",
            'env_key = "FACTORTESTER_AGENT_TOKEN"',
            'wire_api = "responses"',
            "",
            "[shell_environment_policy]",
            "# Keep the provider token in app-server only; do not pass it to shell tools.",
            "ignore_default_excludes = false",
            "",
        ])
        path = self.runtime.codex_home / "config.toml"
        fd, temporary = tempfile.mkstemp(
            prefix="factortester-agent-config-",
            suffix=".tmp",
            dir=self.runtime.codex_home,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(config)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def command(self) -> list[str]:
        return self.runtime.command(self.codex_binary)

    def environment(self) -> dict[str, str]:
        secret = str(self.provider.get("secret") or "")
        if not secret:
            raise AgentAppServerError("Agent provider token is unavailable")
        environment = self.runtime.environment()
        # Do not inherit credentials from the Manager process.  The child gets
        # exactly one token through the private env key named by config.toml.
        for key in (
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "FACTORTESTER_AGENT_TOKEN",
        ):
            environment.pop(key, None)
        environment["FACTORTESTER_AGENT_TOKEN"] = secret
        if self.proxy_url:
            self._set_proxy_environment(environment)
        cli = str(self.factor_tester_cli or "").strip()
        if cli:
            cli_path = Path(cli).expanduser()
            if cli_path.parent != Path("."):
                environment["PATH"] = os.pathsep.join([
                    str(cli_path.parent),
                    environment.get("PATH", ""),
                ]).rstrip(os.pathsep)
            environment["FACTORTESTER_CLI"] = cli
        return environment

    def _set_proxy_environment(self, environment: dict[str, str]) -> None:
        """Scope the optional proxy to the Profile app-server child."""
        for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy",
        ):
            environment[key] = self.proxy_url
        bypass = {
            "127.0.0.1", "localhost", "::1",
            "10.77.0.0/16", "10.79.0.0/16", "172.30.0.0/16",
        }
        for key in (
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
            "FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT",
        ):
            hostname = urlsplit(str(environment.get(key) or "")).hostname
            if hostname:
                bypass.add(hostname)
        existing = str(environment.get("NO_PROXY") or environment.get("no_proxy") or "")
        bypass.update(item.strip() for item in existing.split(",") if item.strip())
        value = ",".join(sorted(bypass))
        environment["NO_PROXY"] = value
        environment["no_proxy"] = value
