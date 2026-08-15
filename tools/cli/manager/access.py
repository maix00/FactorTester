"""Local readiness checks for server-declared operator access methods.

The Manager CLI never retrieves or prints a secret.  It only checks whether a
server-declared local credential source appears to be available, then leaves
execution to the separately authorized operator tooling.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any, Mapping


def access_method_status(method: Mapping[str, Any]) -> dict[str, Any]:
    """Return a redacted local readiness projection for one method."""
    method_id = str(method.get("id") or "").strip()
    auth = method.get("auth")
    credential = _credential_status(auth if isinstance(auth, Mapping) else {})
    script = method.get("script")
    script_status = {
        "declared": isinstance(script, Mapping),
    }
    if isinstance(script, Mapping):
        script_status.update({
            "id": str(script.get("id") or ""),
            "filename": str(script.get("filename") or ""),
            "sha256": str(script.get("sha256") or ""),
            "requires_auth": bool(script.get("requires_auth", True)),
        })
    credential_ready = credential["state"] == "ready"
    ready = credential_ready
    if script_status["declared"] and not script_status["requires_auth"]:
        # A public, digest-checked script can be downloaded without an
        # operator credential even when the method itself has one.
        ready = True
    return {
        "method_id": method_id,
        "kind": str(method.get("kind") or ""),
        "label": str(method.get("label") or method_id),
        "credential": credential,
        "script": script_status,
        "ready": bool(ready),
    }


def _credential_status(auth: Mapping[str, Any]) -> dict[str, Any]:
    required = bool(auth.get("required", True)) if auth else False
    provider = str(auth.get("provider") or "").strip()
    profile = str(auth.get("profile") or "").strip()
    result: dict[str, Any] = {
        "required": required,
        "provider": provider,
        "profile": profile,
        "source": str(auth.get("source") or "").strip(),
        "state": "ready" if not required else "unknown",
    }
    if not required:
        result["message"] = "不需要本机凭证"
        return result
    source = result["source"]
    if source == "environment":
        names = [str(item).strip() for item in auth.get("environment") or ()]
        missing = [name for name in names if not os.environ.get(name, "").strip()]
        result["environment"] = names
        result["missing"] = missing
        result["state"] = "ready" if names and not missing else "missing"
        result["message"] = (
            "本机环境凭证已就绪"
            if result["state"] == "ready"
            else "本机缺少服务器声明的环境凭证"
        )
        return result
    if source in {"local-keychain", "macos-keychain"}:
        return _keychain_status(auth, result)
    if source == "docker-context":
        return _docker_context_status(auth, result)
    if source == "aliyun-cli":
        result["state"] = "unknown" if _command_exists(
            str(auth.get("executable") or "aliyun")
        ) else "missing"
        result["message"] = (
            "本机阿里云 CLI 可用，但未读取其凭证；请先通过阿里云 CLI 验证"
            if result["state"] == "unknown"
            else "本机未找到服务器声明的阿里云 CLI"
        )
        return result
    result["message"] = "服务器声明了未知的本机凭证来源"
    return result


def _docker_context_status(
    auth: Mapping[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    context = str(auth.get("profile") or "").strip()
    if not context:
        result["state"] = "missing"
        result["message"] = "服务器声明缺少 Docker Context profile"
        return result
    if not _command_exists("docker"):
        result["state"] = "missing"
        result["message"] = "本机未找到 Docker CLI"
        return result
    completed = subprocess.run(
        ["docker", "context", "inspect", context],
        capture_output=True,
        text=True,
        check=False,
    )
    result["state"] = "ready" if completed.returncode == 0 else "missing"
    result["message"] = (
        "本机 Docker Context 已登记"
        if result["state"] == "ready"
        else "本机没有服务器声明的 Docker Context"
    )
    return result


def _keychain_status(
    auth: Mapping[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if platform.system() != "Darwin":
        result["state"] = "unknown"
        result["message"] = "当前系统不是 macOS，无法检查 macOS Keychain"
        return result
    service = str(auth.get("service") or "").strip()
    account = str(auth.get("account") or auth.get("profile") or "").strip()
    if not service or not account:
        result["state"] = "unknown"
        result["message"] = "服务器声明缺少 Keychain service/account 标识"
        return result
    completed = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account],
        capture_output=True,
        text=True,
        check=False,
    )
    result["state"] = "ready" if completed.returncode == 0 else "missing"
    result["message"] = (
        "本机 Keychain 凭证已登记"
        if result["state"] == "ready"
        else "本机 Keychain 中没有该服务器所需凭证"
    )
    return result


def _command_exists(command: str) -> bool:
    return bool(command and shutil.which(command))


def select_access_methods(
    methods: object,
    *,
    method_id: str = "",
) -> list[dict[str, Any]]:
    """Validate the server projection and optionally select one method."""
    values = (
        [item for item in methods if isinstance(item, Mapping)]
        if isinstance(methods, (list, tuple))
        else []
    )
    selected = str(method_id or "").strip()
    if selected:
        values = [item for item in values if str(item.get("id") or "") == selected]
        if not values:
            raise ValueError(f"服务器没有声明连接方式: {selected}")
    return [access_method_status(item) for item in values]


__all__ = ["access_method_status", "select_access_methods"]
