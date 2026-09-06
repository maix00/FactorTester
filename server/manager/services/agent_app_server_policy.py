"""Profile boundary for requests forwarded to Codex app-server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from server.manager.services.agent_app_server_errors import (
    AgentAppServerError,
    PUBLIC_RPC_METHODS,
)
from server.manager.services.agent_skill_protocol import AgentSkillProtocol
from server.manager.services.agent_skill_runtime import AgentSkillRuntime
from server.manager.services.profile_agent_sandbox import SANDBOX_WORKSPACE


_POLICY_OVERRIDE_KEYS = frozenset({
    "approvalpolicy",
    "sandbox",
    "sandboxpolicy",
    "permissions",
    "permissionprofile",
    "permissionprofileid",
    "networkaccess",
    "additionalpermissions",
    "runtimeworkspaceroots",
    "selectedcapabilityroots",
    "modelprovider",
    "modelproviderid",
    "modelproviders",
    "shellenvironmentpolicy",
    "bypassapprovalsandsandbox",
    "dangerfullaccess",
})


def _normalized_key(value: object) -> str:
    return "".join(
        character for character in str(value or "").casefold()
        if character.isalnum()
    )


class AgentAppServerPolicy:
    """Normalize browser requests to one Profile-owned execution boundary."""

    def __init__(
        self,
        runtime: AgentSkillRuntime,
        protocol: AgentSkillProtocol,
    ) -> None:
        self.runtime = runtime
        self.protocol = protocol

    def prepare(
        self,
        method: str,
        params: Mapping[str, object],
    ) -> dict[str, Any]:
        if method not in PUBLIC_RPC_METHODS:
            raise AgentAppServerError("app-server method is not exposed")
        payload = dict(params)
        self._reject_policy_overrides(payload)
        self._validate_cwd(payload)

        if method == "thread/list":
            payload["cwd"] = str(SANDBOX_WORKSPACE)
        elif method in {"thread/start", "thread/resume", "turn/start"}:
            payload["cwd"] = str(SANDBOX_WORKSPACE)

        if method in {"turn/start", "turn/steer"}:
            payload["input"] = self._text_inputs(payload)
        if method == "turn/steer" and "skill_ids" in payload:
            raise AgentAppServerError("turn/steer does not accept skill_ids")
        if method == "turn/start":
            self._append_selected_skills(payload)
        return payload

    @staticmethod
    def _reject_policy_overrides(payload: Mapping[str, object]) -> None:
        for key in payload:
            if _normalized_key(key) in _POLICY_OVERRIDE_KEYS:
                raise AgentAppServerError(
                    f"app-server policy override is not allowed: {key}"
                )

    def _validate_cwd(self, payload: Mapping[str, object]) -> None:
        if "cwd" not in payload:
            return
        requested = str(payload.get("cwd") or "").strip()
        if not requested:
            return
        try:
            resolved = Path(requested).expanduser().resolve()
        except OSError as exc:
            raise AgentAppServerError("Agent request cwd is invalid") from exc
        if resolved != self.runtime.workspace_root:
            raise AgentAppServerError(
                "Agent request cwd must be its Profile workspace"
            )

    @staticmethod
    def _text_inputs(payload: dict[str, Any]) -> list[dict[str, str]]:
        raw = payload.pop("input", None)
        prompt = payload.pop("prompt", None)
        if raw is None:
            text = str(prompt or "").strip()
            if not text:
                raise AgentAppServerError("turn requires prompt or input")
            return [{"type": "text", "text": text}]
        if prompt not in (None, ""):
            raise AgentAppServerError("turn cannot include both prompt and input")
        if not isinstance(raw, list) or not raw:
            raise AgentAppServerError("turn input must be a non-empty list")
        result: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise AgentAppServerError("turn input items must be objects")
            if item.get("type") != "text":
                raise AgentAppServerError(
                    "only text input is available in the Profile Agent chat"
                )
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise AgentAppServerError("text input must be a non-empty string")
            result.append({"type": "text", "text": text})
        return result

    def _append_selected_skills(self, payload: dict[str, Any]) -> None:
        skill_ids = payload.pop("skill_ids", [])
        if not isinstance(skill_ids, list):
            raise AgentAppServerError("skill_ids must be a list")
        payload["input"].extend(
            self.protocol.turn_skill_input(str(skill_id))
            for skill_id in skill_ids
        )
