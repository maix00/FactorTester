"""Profile-scoped Codex app-server configuration and child environment."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from server.manager.services.agent_app_server_errors import AgentAppServerError
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
    ) -> None:
        self.runtime = runtime
        self.provider = dict(provider)
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"

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
        return environment
