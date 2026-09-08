"""Profile-scoped Codex app-server configuration and child environment."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from server.manager.services.agent_app_server_errors import AgentAppServerError
from server.manager.services.agent_provider_health import (
    AgentProviderHealth,
    AgentProviderHealthError,
)
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.services.profile_agent_sandbox import ProfileAgentSandbox
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile


# Static runtime instructions, separate from user turn input. Page data stays
# on demand so ordinary messages do not repeatedly carry schemas or candidates.
_PAGE_ASSISTANCE_INSTRUCTION = """你是 FactorTester 研究助手。
需要操作页面时，先用 `factortester assist inspect` 获取获准页面和当前页；用 `--tab-id` 明确目标，不依赖页面是否激活。
按页面声明的 schema 修改草稿，经 validate、apply 后以 applied 回执确认；保留未请求的字段，不猜参数。
研究和报告操作用 `factortester research --help` 查询。节点、候选和正文按需读取，不全量枚举；不绕过权限。"""


def _toml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


class AgentAppServerLaunch:
    """Build a launch without persisting a provider token."""

    def __init__(
        self,
        *,
        runtime: AgentSkillRuntime,
        provider: Mapping[str, object],
        codex_binary: str,
        factor_tester_cli: str = "",
        factor_tester_auth: Mapping[str, object] | None = None,
        proxy_url: str = "",
    ) -> None:
        self.runtime = runtime
        self.provider = dict(provider)
        self.codex_binary = str(codex_binary or "codex").strip() or "codex"
        configured_cli = str(
            factor_tester_cli or os.environ.get("FACTORTESTER_CLI") or ""
        ).strip()
        self.factor_tester_cli = configured_cli or str(
            shutil.which("factortester") or ""
        )
        self.factor_tester_auth = dict(factor_tester_auth or {})
        codex_home = Path(getattr(self.runtime, "codex_home", "."))
        self.factor_tester_config_path = codex_home / "factor-tester-cli.json"
        self.factor_tester_capability_path = codex_home / "factor-tester-agent.json"
        self.factor_tester_ca_path = codex_home / "factor-tester-ca.pem"
        self.proxy_url = str(proxy_url or "").strip()

    @staticmethod
    def _executable(value: str, label: str) -> str:
        resolved = shutil.which(str(value or "").strip())
        if not resolved:
            raise AgentAppServerError(
                f"{label} executable is unavailable",
                code="runtime_missing",
            )
        return resolved

    def preflight(
        self,
        *,
        check_provider: bool = True,
        require_factor_tester: bool = True,
    ) -> dict[str, object]:
        """Validate all local and remote prerequisites before spawning Codex."""
        codex = self._executable(self.codex_binary, "Codex")
        factor_tester = (
            self._executable(self.factor_tester_cli, "FactorTester CLI")
            if require_factor_tester
            else None
        )
        if not check_provider:
            return {
                "codex": codex,
                "factor_tester_cli": factor_tester,
                "provider": None,
            }
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
                f"Agent provider preflight failed: {exc}",
                code=exc.code,
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
        config = "\n".join(
            [
                f"model = {_toml_string(model)}",
                f"developer_instructions = {_toml_string(_PAGE_ASSISTANCE_INSTRUCTION)}",
                'model_provider = "factortester"',
                'approval_policy = "never"',
                # FactorTester already launches Codex inside a Profile-only
                # Bubblewrap mount namespace with a private /tmp.  Asking
                # Codex for workspace-write here would require a second,
                # nested Bubblewrap user namespace and makes every shell tool
                # fail.  "danger-full-access" is scoped to that outer
                # namespace, not to the Manager host/container filesystem.
                'sandbox_mode = "danger-full-access"',
                "",
                "[model_providers.factortester]",
                'name = "FactorTester provider"',
                f"base_url = {_toml_string(base_url)}",
                'env_key = "FACTORTESTER_AGENT_TOKEN"',
                'wire_api = "responses"',
                "",
                "[shell_environment_policy]",
                (
                    "# Keep the provider token in app-server only; "
                    "do not pass it to shell tools."
                ),
                "ignore_default_excludes = false",
                "",
            ]
        )
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
        sandbox = ProfileAgentSandbox(
            workspace_root=self.runtime.workspace_root,
            skill_sources=[
                value["source_path"]
                for value in self.runtime.selected_bindings().values()
            ],
        )
        return sandbox.command(self.runtime.command(self.codex_binary))

    def write_factor_tester_config(self) -> None:
        """Materialize a private local CLI config and Agent capability."""
        if not self.factor_tester_auth:
            return
        base_url = (
            str(self.factor_tester_auth.get("base_url") or "").strip().rstrip("/")
        )
        token = str(self.factor_tester_auth.get("token") or "").strip()
        profile_id = str(self.factor_tester_auth.get("profile_id") or "").strip()
        claim_id = str(self.factor_tester_auth.get("claim_id") or "").strip()
        principal = str(self.factor_tester_auth.get("principal") or "").strip()
        if not all((base_url, token, profile_id, claim_id, principal)):
            raise AgentAppServerError(
                "Profile Agent FactorTester capability is incomplete"
            )
        self._write_private_json(
            self.factor_tester_config_path,
            {"base_url": base_url},
        )
        self._write_private_json(
            self.factor_tester_capability_path,
            {
                "schema_version": 1,
                "kind": "profile-agent",
                "base_url": base_url,
                "token": token,
                "profile_id": profile_id,
                "claim_id": claim_id,
            },
        )
        self._ensure_local_profile(profile_id, principal)
        self._write_factor_tester_ca()

    def _write_factor_tester_ca(self) -> None:
        """Trust the configured local data listener, retaining system roots.

        Only public certificates enter the isolated workspace. The private
        server key and the host's global trust configuration remain untouched.
        """
        certificate = (os.environ.get("FACTORTESTER_ARTIFACT_TLS_CERT")
                       or os.environ.get("FACTORTESTER_MANAGER_TLS_CERT"))
        if not certificate:
            self.factor_tester_ca_path.unlink(missing_ok=True)
            return
        pem = Path(certificate).read_text(encoding="ascii")
        trust = ssl.create_default_context()
        roots = "".join(ssl.DER_cert_to_PEM_cert(cert)
                        for cert in trust.get_ca_certs(binary_form=True))
        # Validate before replacing the previous file; never suppress TLS
        # verification or silently proceed with malformed deployment material.
        trust.load_verify_locations(cadata=pem)
        self.factor_tester_ca_path.parent.mkdir(parents=True, exist_ok=True)
        self.factor_tester_ca_path.write_text(roots + "\n" + pem, encoding="ascii")
        self.factor_tester_ca_path.chmod(0o600)

    def _ensure_local_profile(self, profile_id: str, principal: str) -> None:
        """Project the current server Profile into its isolated client root."""
        root = self.runtime.factor_tester_client_root
        root.mkdir(parents=True, exist_ok=True)
        store = LocalProfileStore(root)
        existing = {
            str(item.get("profile_id") or ""): item for item in store.list()
        }.get(profile_id)
        if existing is not None:
            binding = existing.get("session_binding") or {}
            if str(binding.get("principal_ref") or "") != principal:
                raise AgentAppServerError(
                    "Profile Agent local projection principal does not match"
                )
            return
        store.save(
            new_local_profile(
                profile_id=profile_id,
                display_name=profile_id,
                workspace_root=Path("/workspace"),
                principal_ref=principal,
            )
        )

    @staticmethod
    def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def cleanup_factor_tester_config(self) -> None:
        """Remove the short-lived Agent credential after the child stops."""
        if not self.factor_tester_auth:
            return
        self.factor_tester_capability_path.unlink(missing_ok=True)
        self.factor_tester_config_path.unlink(missing_ok=True)
        self.factor_tester_ca_path.unlink(missing_ok=True)

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
                environment["PATH"] = os.pathsep.join(
                    [
                        str(cli_path.parent),
                        environment.get("PATH", ""),
                    ]
                ).rstrip(os.pathsep)
            environment["FACTORTESTER_CLI"] = cli
        if self.factor_tester_auth:
            if self.factor_tester_ca_path.is_file():
                environment["SSL_CERT_FILE"] = str(self.factor_tester_ca_path)
            environment["FACTORTESTER_CONFIG"] = str(self.factor_tester_config_path)
            environment["FACTORTESTER_HOME"] = str(
                self.runtime.home_root / "factortester"
            )
            environment["FACTORTESTER_CLIENT_ROOT"] = str(
                self.runtime.factor_tester_client_root
            )
            environment["FACTORTESTER_PROFILE"] = str(
                self.factor_tester_auth.get("profile_id") or ""
            )
            environment["FACTORTESTER_AGENT_CAPABILITY_FILE"] = str(
                self.factor_tester_capability_path
            )
        workspace_root = getattr(self.runtime, "workspace_root", None)
        if workspace_root is None:
            return environment
        return ProfileAgentSandbox(workspace_root=workspace_root).environment(environment)

    def _set_proxy_environment(self, environment: dict[str, str]) -> None:
        """Scope the optional proxy to the Profile app-server child."""
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            environment[key] = self.proxy_url
        bypass = {
            "127.0.0.1",
            "localhost",
            "::1",
            "10.77.0.0/16",
            "10.79.0.0/16",
            "172.30.0.0/16",
        }
        for key in (
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
            "FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT",
        ):
            hostname = urlsplit(str(environment.get(key) or "")).hostname
            if hostname:
                bypass.add(hostname)
        if self.factor_tester_auth:
            hostname = urlsplit(
                str(self.factor_tester_auth.get("base_url") or "")
            ).hostname
            if hostname:
                bypass.add(hostname)
        existing = str(environment.get("NO_PROXY") or environment.get("no_proxy") or "")
        bypass.update(item.strip() for item in existing.split(",") if item.strip())
        value = ",".join(sorted(bypass))
        environment["NO_PROXY"] = value
        environment["no_proxy"] = value
