"""Profile runtime bindings, provider connections, and Agent claims."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from server.manager.services.agent_provider_health import (
    AgentProviderHealth,
)
from server.manager.services.agent_provider_network import (
    AgentProviderProxyUnavailable,
    resolve_provider_proxy,
)
from server.manager.services.agent_skill_catalog import (
    AgentSkillCatalog,
    AgentSkillCatalogError,
)
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.services.agent_workspace import (
    ensure_server_profile_workspace,
    profile_workspace_relative_path,
)
from server.manager.services.assistance_drafts import AssistanceDraftStore
from server.manager.services.profile_workspace_browser import (
    ProfileWorkspaceBrowser,
)
from server.manager.storage.agent_conversation_store import AgentConversationStore
from server.manager.storage.agent_provider_store import (
    AgentProviderStore,
    ProviderStoreError,
)
from server.manager.storage.agent_skill_store import AgentSkillStore
from server.manager.storage.profile_runtime_store import (
    ProfileRuntimeError,
    ProfileRuntimeStore,
)


class AgentProfileService:
    """Coordinate the local state for one Manager's Agent-capable Profiles."""

    def __init__(
        self,
        *,
        db_path,
        provider_key_path,
        data_root,
        server_id: str,
        skill_source_root=None,
        skill_manifest_path=None,
        proxy_url_provider: Callable[[], str] | None = None,
        agent_session_issuer: Callable[[str, str, str], dict[str, object]]
        | None = None,
        agent_session_revoker: Callable[[str], None] | None = None,
        manager_endpoint_provider: Callable[[], str] | None = None,
        profile_factor_worktree_preparer: Callable[
            [str, str, Path, Path], dict[str, Any]
        ]
        | None = None,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise ValueError("server_id is required")
        self.data_root = data_root
        self.proxy_url_provider = proxy_url_provider
        self.agent_session_issuer = agent_session_issuer
        self.agent_session_revoker = agent_session_revoker
        self.manager_endpoint_provider = manager_endpoint_provider
        self.profile_factor_worktree_preparer = profile_factor_worktree_preparer
        self.runtime_store = ProfileRuntimeStore(db_path)
        self.conversation_store = AgentConversationStore(db_path)
        self.provider_store = AgentProviderStore(db_path, provider_key_path)
        source_root = skill_source_root
        if source_root is None:
            source_root = Path(__file__).resolve().parents[3]
        manifest = skill_manifest_path
        if manifest is None:
            manifest = (
                Path(source_root) / "server" / "manager" / "skills" / "catalog.json"
            )
        elif not Path(manifest).is_absolute():
            manifest = Path(source_root) / manifest
        self.skill_catalog = AgentSkillCatalog(source_root, manifest)
        self.skill_store = AgentSkillStore(db_path)
        self.workspace_browser = ProfileWorkspaceBrowser(
            data_root=data_root,
            runtime_store=self.runtime_store,
            server_id=self.server_id,
        )

    @staticmethod
    def _profile_id(profile: dict[str, Any]) -> str:
        return str(profile.get("profile_id") or "").strip()

    def _default_runtime(
        self,
        principal: str,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Infer legacy metadata without silently assigning a server Profile."""
        runtime_kind = str(profile.get("runtime_kind") or "").strip()
        execution_server_id = str(profile.get("execution_server_id") or "").strip()
        execution_device_id = str(profile.get("execution_device_id") or "").strip()
        server_metadata = profile.get("server")
        if not execution_server_id and isinstance(server_metadata, dict):
            execution_server_id = str(server_metadata.get("server_id") or "").strip()
        if runtime_kind not in {"client", "server"}:
            server = profile.get("server")
            if (
                execution_server_id
                or isinstance(server, dict)
                and server.get("server_id")
            ):
                runtime_kind = "server"
            else:
                runtime_kind = "client"
        executor_id = (
            execution_server_id if runtime_kind == "server" else execution_device_id
        )
        profile_id = self._profile_id(profile)
        return {
            "profile_id": profile_id,
            "runtime_kind": runtime_kind,
            "executor_id": executor_id,
            "workspace_relpath": profile_workspace_relative_path(
                principal,
                profile_id,
            )
            if profile_id
            else "",
            "configured": bool(executor_id),
            "source": "profile",
        }

    def enrich(
        self,
        principal: str,
        profiles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        owner = str(principal or "").strip()
        runtimes = self.runtime_store.runtimes(owner)
        result: list[dict[str, Any]] = []
        for original in profiles:
            if not isinstance(original, dict):
                continue
            profile = dict(original)
            profile_id = self._profile_id(profile)
            if not profile_id:
                continue
            runtime = runtimes.get(profile_id) or self._default_runtime(owner, profile)
            claim = self.runtime_store.active_claim(owner, profile_id)
            profile["runtime"] = {
                "profile_id": profile_id,
                "runtime_kind": runtime.get("runtime_kind", "client"),
                "executor_id": runtime.get("executor_id", ""),
                "workspace_relpath": runtime.get("workspace_relpath", ""),
                "configured": bool(runtime.get("executor_id")),
                "server_id": self.server_id
                if runtime.get("runtime_kind") == "server"
                else "",
            }
            profile["active_claim"] = self._public_claim(claim)
            result.append(profile)
        return result

    @staticmethod
    def _public_claim(claim: dict[str, Any] | None) -> dict[str, Any] | None:
        if not claim:
            return None
        return {
            "claim_id": claim.get("claim_id", ""),
            "runtime_kind": claim.get("runtime_kind", ""),
            "executor_id": claim.get("executor_id", ""),
            "agent_id": claim.get("agent_id", ""),
            "provider_id": claim.get("provider_id", ""),
            "agent_runtime": claim.get("agent_runtime", "codex"),
            "provider_protocol": claim.get("provider_protocol", "openai_responses"),
            "provider_model": claim.get("provider_model", ""),
            "provider_config_version": claim.get("provider_config_version", 0),
            "claimed_at": claim.get("claimed_at", 0),
            "last_heartbeat_at": claim.get("last_heartbeat_at", 0),
            "status": claim.get("status", ""),
        }

    def bind_runtime(
        self,
        principal: str,
        profile_id: str,
        *,
        runtime_kind: str,
        executor_id: str,
    ) -> dict[str, Any]:
        runtime = str(runtime_kind or "").strip()
        executor = str(executor_id or "").strip()
        if runtime == "server" and executor != self.server_id:
            raise ProfileRuntimeError("server Profile must be bound to this Manager")
        if runtime == "client" and not executor:
            raise ProfileRuntimeError("client Profile requires a device_id")
        relative = profile_workspace_relative_path(principal, profile_id)
        if runtime == "server":
            # Runtime binding is the ownership/workspace operation.  Skill
            # projection is deliberately performed when the Profile selects
            # Skills or when its Agent starts.  Keeping those operations
            # separate means a missing optional Skill cannot prevent the
            # server workspace from being created or the runtime binding from
            # being saved.
            ensure_server_profile_workspace(
                self.data_root,
                principal,
                profile_id,
            )
        return self.runtime_store.bind(
            principal,
            profile_id,
            runtime_kind=runtime,
            executor_id=executor,
            workspace_relpath=relative,
        )

    def require_local_server_runtime(
        self,
        principal: str,
        profile_id: str,
    ) -> dict[str, Any]:
        """Authorize operations reserved for a Profile hosted by this Manager."""
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            raise ProfileRuntimeError("Profile is not bound to a server runtime")
        if str(runtime.get("executor_id") or "") != self.server_id:
            raise ProfileRuntimeError("Profile belongs to another server")
        return runtime

    def providers(
        self,
        principal: str,
        *,
        runtime_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.provider_store.list(
            principal,
            runtime_kind=runtime_kind,
            server_id=self.server_id if runtime_kind == "server" else None,
        )

    def available_skills(self, *, runtime_kind: str = "server") -> list[dict[str, Any]]:
        return self.skill_catalog.public_definitions(runtime_kind)

    def profile_workspace(
        self,
        principal: str,
        profile_id: str,
        relative_path: str = "",
    ) -> dict[str, Any]:
        return self.workspace_browser.list(principal, profile_id, relative_path)

    def profile_workspace_file(
        self,
        principal: str,
        profile_id: str,
        relative_path: str,
    ) -> dict[str, Any]:
        return self.workspace_browser.file_metadata(
            principal,
            profile_id,
            relative_path,
        )

    def delete_profile_workspace_file(
        self,
        principal: str,
        profile_id: str,
        relative_path: str,
    ) -> dict[str, Any]:
        return self.workspace_browser.delete_file(principal, profile_id, relative_path)

    def save_profile_workspace_file(
        self,
        principal: str,
        profile_id: str,
        relative_path: str,
        data: bytes,
        *,
        filename: str = "",
    ) -> dict[str, Any]:
        return self.workspace_browser.write_file(
            principal,
            profile_id,
            relative_path,
            data,
            filename=filename,
        )

    def assistance_drafts(
        self, principal: str, profile_id: str
    ) -> AssistanceDraftStore:
        self.require_local_server_runtime(principal, profile_id)
        workspace = ensure_server_profile_workspace(
            self.data_root, principal, profile_id
        )
        return AssistanceDraftStore(workspace)

    def conversations(
        self,
        principal: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        return self.conversation_store.list(principal, profile_id)

    def set_conversation_sharing(
        self,
        principal: str,
        profile_id: str,
        enabled: bool,
    ) -> bool:
        return self.conversation_store.set_parent_sharing(
            principal,
            profile_id,
            enabled,
        )

    def conversation_sharing(self, principal: str, profile_id: str) -> bool:
        return self.conversation_store.parent_sharing(principal, profile_id)

    def create_conversation(
        self,
        principal: str,
        profile_id: str,
        *,
        title: str = "",
    ) -> dict[str, Any]:
        model_id = ""
        provider_id = self.provider_id_for_profile(principal, profile_id)
        if provider_id:
            provider = self.provider_store.get(principal, provider_id)
            model_id = str((provider or {}).get("default_model") or "")
        return self.conversation_store.create(
            principal,
            profile_id,
            title=title,
            model_id=model_id,
        )

    def select_conversation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        return self.conversation_store.select(
            principal,
            profile_id,
            conversation_id,
        )

    def update_conversation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        preview: str | None = None,
    ) -> dict[str, Any]:
        return self.conversation_store.update(
            principal,
            profile_id,
            conversation_id,
            title=title,
            preview=preview,
        )

    def update_conversation_runtime_settings(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
        *,
        model_id: str,
        reasoning_effort: str,
        service_tier: str,
    ) -> dict[str, Any]:
        return self.conversation_store.update_runtime_settings(
            principal,
            profile_id,
            conversation_id,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
        )

    def delete_conversation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> bool:
        return self.conversation_store.clear(
            principal,
            profile_id,
            conversation_id,
        )

    def conversation(
        self,
        principal: str,
        profile_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        return self.conversation_store.get(
            principal,
            profile_id,
            conversation_id,
        )

    def provider_id_for_profile(self, principal: str, profile_id: str) -> str:
        claim = self.runtime_store.active_claim(principal, profile_id)
        return str(claim.get("provider_id") or "") if claim else ""

    def profile_skills(
        self,
        principal: str,
        profile_id: str,
    ) -> dict[str, Any]:
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None:
            raise ProfileRuntimeError(
                "configure the Profile runtime before selecting Skills"
            )
        runtime_kind = str(runtime.get("runtime_kind") or "")
        definitions = self.skill_catalog.definitions(runtime_kind)
        selected = set(self.skill_store.selected(principal, profile_id))
        return {
            "profile_id": profile_id,
            "runtime_kind": runtime_kind,
            "skills": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"path", "relative_path"}
                }
                | {"selected": item["skill_id"] in selected}
                for item in definitions
            ],
        }

    def selected_skill_bindings(
        self,
        principal: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        """Return selected Skill paths for the future app-server supervisor."""
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None:
            raise ProfileRuntimeError("Profile runtime is not configured")
        selected_ids = self.skill_store.selected(principal, profile_id)
        # An unconfigured Profile may legitimately have no selected Skills.
        # Do not require the complete server catalog just to represent an
        # empty selection; this also keeps binding/claiming resilient while a
        # server image is being repaired.
        if not selected_ids:
            return []
        definitions = {
            item["skill_id"]: item
            for item in self.skill_catalog.definitions(str(runtime["runtime_kind"]))
        }
        return [
            definitions[skill_id]
            for skill_id in selected_ids
            if skill_id in definitions
        ]

    def prepare_server_skill_runtime(
        self,
        principal: str,
        profile_id: str,
        *,
        bindings: list[dict[str, Any]] | None = None,
    ) -> AgentSkillRuntime:
        """Synchronize and return the Profile-local app-server runtime seam."""
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            raise ProfileRuntimeError("Profile is not bound to a server runtime")
        if str(runtime.get("executor_id") or "") != self.server_id:
            raise ProfileRuntimeError("Profile belongs to another server")
        workspace = ensure_server_profile_workspace(
            self.data_root,
            principal,
            profile_id,
        )
        runtime_state = AgentSkillRuntime(workspace)
        runtime_state.sync(
            self.selected_skill_bindings(principal, profile_id)
            if bindings is None
            else bindings,
        )
        return runtime_state

    def server_agent_context(
        self,
        principal: str,
        profile_id: str,
    ) -> dict[str, Any]:
        """Return private launch material for the Manager-owned supervisor."""
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            raise ProfileRuntimeError("Profile is not bound to a server runtime")
        if str(runtime.get("executor_id") or "") != self.server_id:
            raise ProfileRuntimeError("Profile belongs to another server")
        claim = self.runtime_store.active_claim(principal, profile_id)
        if claim is None:
            raise ProfileRuntimeError("claim the Profile before starting its Agent")
        provider_id = str(claim.get("provider_id") or "").strip()
        provider = self.provider_store.get(
            principal,
            provider_id,
            include_secret=True,
        )
        if provider is None or not provider.get("enabled"):
            raise ProviderStoreError("claimed Agent provider is unavailable")
        if provider.get("runtime_kind") != "server":
            raise ProviderStoreError("claimed Agent provider is not a server provider")
        if provider.get("server_id") != self.server_id:
            raise ProviderStoreError("claimed Agent provider belongs to another server")
        if float(claim.get("provider_config_version") or 0) == 0:
            claim = self.runtime_store.freeze_legacy_provider_binding(
                str(claim.get("claim_id") or ""),
                provider_id=str(provider.get("provider_id") or ""),
                agent_runtime=str(provider.get("agent_runtime") or "codex"),
                provider_protocol=str(provider.get("protocol") or "openai_responses"),
                provider_model=str(provider.get("default_model") or ""),
                provider_config_version=float(provider.get("updated_at") or 0),
            )
        if float(provider.get("updated_at") or 0) != float(
            claim.get("provider_config_version") or 0
        ):
            raise ProviderStoreError(
                "claimed Agent provider changed; release and reclaim the Profile"
            )
        skill_runtime = self.prepare_server_skill_runtime(
            principal,
            profile_id,
        )
        if self.profile_factor_worktree_preparer is not None:
            self.profile_factor_worktree_preparer(
                principal,
                profile_id,
                skill_runtime.workspace_root,
                skill_runtime.factor_tester_client_root,
            )
        factor_tester_auth: dict[str, object] = {}
        if self.agent_session_issuer is not None:
            endpoint = ""
            if self.manager_endpoint_provider is not None:
                endpoint = (
                    str(self.manager_endpoint_provider() or "").strip().rstrip("/")
                )
            if not endpoint:
                raise ProfileRuntimeError(
                    "local Manager endpoint is unavailable for the Profile Agent"
                )
            agent_session = self.agent_session_issuer(
                principal,
                profile_id,
                str(claim.get("claim_id") or "").strip(),
            )
            factor_tester_auth = {
                "base_url": endpoint,
                "token": str(agent_session.get("token") or "").strip(),
                "profile_id": profile_id,
                "claim_id": str(claim.get("claim_id") or "").strip(),
                "principal": principal,
            }
            if not factor_tester_auth["token"]:
                raise ProfileRuntimeError(
                    "Manager did not issue a Profile Agent session"
                )
        return {
            "runtime": runtime,
            "claim": claim,
            "provider": provider,
            "factor_tester_auth": factor_tester_auth,
            "skill_runtime": skill_runtime,
        }

    def server_thread_read_context(
        self,
        principal: str,
        profile_id: str,
        provider_id: str = "",
    ) -> dict[str, Any]:
        """Return local material needed to read a persisted Provider thread.

        Historical reads are authorized by the conversation catalog and do
        not require an active Agent claim.  They also never call the model
        provider, so a removed provider connection must not make the Profile's
        locally persisted Codex thread unreadable.
        """
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            raise ProfileRuntimeError("Profile is not bound to a server runtime")
        if str(runtime.get("executor_id") or "") != self.server_id:
            raise ProfileRuntimeError("Profile belongs to another server")
        identifier = str(provider_id or "").strip()
        provider = (
            self.provider_store.get(
                principal,
                identifier,
                include_secret=True,
            )
            if identifier
            else None
        )
        if provider is None:
            # Codex requires a syntactically complete provider configuration
            # at process startup even though thread/read performs no network
            # request.  These inert values never leave the child process.
            provider = {
                "provider_id": identifier or "history-only",
                "runtime_kind": "server",
                "server_id": self.server_id,
                "protocol": "openai_responses",
                "default_model": "history-only",
                "base_url": "http://127.0.0.1.invalid",
                "secret": "history-only",
                "enabled": False,
            }
        return {
            "runtime": runtime,
            "provider": provider,
            "skill_runtime": self.prepare_server_skill_runtime(
                principal,
                profile_id,
            ),
        }

    def revoke_agent_session(self, token: str) -> None:
        """Revoke one Manager-issued CLI capability after Agent shutdown."""
        if self.agent_session_revoker is None:
            return
        value = str(token or "").strip()
        if value:
            self.agent_session_revoker(value)

    def set_profile_skills(
        self,
        principal: str,
        profile_id: str,
        skill_ids: list[str],
    ) -> dict[str, Any]:
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None:
            raise ProfileRuntimeError(
                "configure the Profile runtime before selecting Skills"
            )
        if self.runtime_store.active_claim(principal, profile_id) is not None:
            raise ProfileRuntimeError(
                "release the active Agent before changing Profile Skills"
            )
        runtime_kind = str(runtime.get("runtime_kind") or "")
        definitions = {
            item["skill_id"]: item
            for item in self.skill_catalog.definitions(runtime_kind)
        }
        requested = sorted(
            {
                str(value or "").strip()
                for value in skill_ids
                if str(value or "").strip()
            }
        )
        unknown = [skill_id for skill_id in requested if skill_id not in definitions]
        if unknown:
            raise AgentSkillCatalogError(
                "Skill is not installed or is not available to this runtime: "
                + ", ".join(unknown)
            )
        selected_bindings = [definitions[skill_id] for skill_id in requested]
        if runtime_kind == "server":
            self.prepare_server_skill_runtime(
                principal,
                profile_id,
                bindings=selected_bindings,
            )
        selected = self.skill_store.replace(principal, profile_id, requested)
        return self.profile_skills(principal, profile_id) | {
            "selected_skill_ids": selected
        }

    def save_provider(
        self,
        principal: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        runtime = str(payload.get("runtime_kind") or "server").strip()
        if runtime == "server":
            payload = {**payload, "server_id": self.server_id}
        elif runtime == "client" and self.server_id != "local":
            raise ProviderStoreError(
                "client provider credentials must be saved by the client runtime"
            )
        return self.provider_store.save(
            principal,
            payload,
            default_server_id=self.server_id,
        )

    def test_provider(
        self,
        principal: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        """Test a Provider API key without persisting or returning its secret."""
        if not isinstance(payload, dict):
            raise ProviderStoreError("provider must be an object")
        runtime = str(payload.get("runtime_kind") or "server").strip()
        if runtime == "server":
            payload = {**payload, "server_id": self.server_id}
        elif runtime == "client" and self.server_id != "local":
            raise ProviderStoreError(
                "client provider credentials must be tested by the client runtime"
            )
        candidate = self.provider_store.candidate(
            principal,
            payload,
            default_server_id=self.server_id,
        )
        try:
            proxy_url = resolve_provider_proxy(
                candidate,
                self.proxy_url_provider,
            )
        except AgentProviderProxyUnavailable as exc:
            raise ProviderStoreError(str(exc), code=exc.code) from exc
        if proxy_url:
            return AgentProviderHealth.test(candidate, proxy_url=proxy_url)
        return AgentProviderHealth.test(candidate)

    def profile_provider_health(
        self,
        principal: str,
        profile_id: str,
    ) -> dict[str, Any]:
        """Explicitly inspect the Provider bound to one Profile."""
        provider_id = self.provider_id_for_profile(principal, profile_id)
        provider = (
            self.provider_store.get(
                principal,
                provider_id,
                include_secret=True,
            )
            if provider_id
            else None
        )
        if provider is None:
            raise ProviderStoreError("Profile Agent provider is unavailable")
        try:
            proxy_url = resolve_provider_proxy(provider, self.proxy_url_provider)
        except AgentProviderProxyUnavailable as exc:
            raise ProviderStoreError(str(exc), code=exc.code) from exc
        if proxy_url:
            return AgentProviderHealth.test(provider, proxy_url=proxy_url)
        return AgentProviderHealth.test(provider)

    def delete_provider(self, principal: str, provider_id: str) -> bool:
        for claim in self.runtime_store.claims(principal):
            if claim.get("provider_id") == provider_id:
                raise ProviderStoreError(
                    "release the active Agent before deleting its provider"
                )
        return self.provider_store.delete(principal, provider_id)

    def duplicate_provider(
        self,
        principal: str,
        provider_id: str,
    ) -> dict[str, Any]:
        return self.provider_store.duplicate(principal, provider_id)

    def claim(
        self,
        principal: str,
        profile_id: str,
        *,
        provider_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        if not str(provider_id or "").strip():
            raise ProviderStoreError("provider_id is required to claim a Profile")
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None:
            raise ProfileRuntimeError("Profile runtime is not configured")
        runtime_kind = str(runtime.get("runtime_kind") or "")
        executor_id = str(runtime.get("executor_id") or "")
        if runtime_kind == "server" and executor_id != self.server_id:
            raise ProfileRuntimeError("Profile belongs to another server")
        if provider_id:
            provider = self.provider_store.get(principal, provider_id)
            if provider is None or not provider.get("enabled"):
                raise ProviderStoreError("provider is unavailable")
            if provider.get("runtime_kind") != runtime_kind:
                raise ProviderStoreError(
                    "provider runtime does not match Profile runtime"
                )
            if runtime_kind == "server" and provider.get("server_id") != self.server_id:
                raise ProviderStoreError("provider belongs to another server")
        if runtime_kind == "server":
            self.prepare_server_skill_runtime(principal, profile_id)
        claim = self.runtime_store.claim(
            principal,
            profile_id,
            runtime_kind=runtime_kind,
            executor_id=executor_id,
            provider_id=provider_id,
            agent_runtime=str(provider.get("agent_runtime") or "codex"),
            provider_protocol=str(provider.get("protocol") or "openai_responses"),
            provider_model=str(provider.get("default_model") or ""),
            provider_config_version=float(provider.get("updated_at") or 0),
            agent_id=agent_id,
        )
        return {
            "runtime": runtime,
            "claim": self._public_claim(claim),
            "selected_skill_ids": [
                item["skill_id"]
                for item in self.selected_skill_bindings(principal, profile_id)
            ],
        }

    def heartbeat(self, principal: str, claim_id: str, agent_id: str) -> dict[str, Any]:
        return {
            "claim": self._public_claim(
                self.runtime_store.heartbeat(principal, claim_id, agent_id=agent_id),
            )
        }

    def release(
        self,
        principal: str,
        claim_id: str,
        *,
        agent_id: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        return {
            "released": self.runtime_store.release(
                principal,
                claim_id,
                agent_id=agent_id,
                force=force,
            ),
        }

    def pause(
        self,
        principal: str,
        claim_id: str,
        *,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """Stop a server Agent while retaining its Profile ownership."""
        return {
            "paused": self.runtime_store.pause(
                principal,
                claim_id,
                agent_id=agent_id,
            ),
        }

    def pause_server_agent(self, principal: str, profile_id: str) -> dict[str, Any]:
        """Pause the claim owned by a Manager-hosted Profile Agent."""
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            return {"paused": False}
        claim = self.runtime_store.active_claim(principal, profile_id)
        if claim is None:
            return {"paused": False}
        return self.pause(
            principal,
            str(claim["claim_id"]),
            agent_id=str(claim["agent_id"]),
        )

    def claims(self, principal: str) -> list[dict[str, Any]]:
        return [
            self._public_claim(item) or {}
            for item in self.runtime_store.claims(principal)
        ]
