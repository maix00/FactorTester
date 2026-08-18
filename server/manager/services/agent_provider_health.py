"""Non-destructive health checks for OpenAI Responses-compatible providers."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen


class AgentProviderHealthError(ValueError):
    """A provider cannot be used by a Profile Agent."""


class AgentProviderHealth:
    """Check credentials and model availability without running a model turn."""

    MAX_RESPONSE_BYTES = 2 * 1024 * 1024

    @classmethod
    def test(
        cls,
        provider: Mapping[str, object],
        *,
        timeout: float = 10.0,
        proxy_url: str = "",
    ) -> dict[str, Any]:
        protocol = str(provider.get("protocol") or "").strip()
        if protocol != "openai_compatible":
            raise AgentProviderHealthError(
                "only OpenAI Responses-compatible providers are supported"
            )
        base_url = str(provider.get("base_url") or "").strip().rstrip("/")
        model = str(provider.get("default_model") or "").strip()
        secret = str(provider.get("secret") or "")
        if not base_url or not model or not secret:
            raise AgentProviderHealthError(
                "provider address, default model, and API key are required"
            )
        endpoint = f"{base_url}/models"
        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {secret}",
            },
            method="GET",
        )
        try:
            opener = (
                build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
                if str(proxy_url or "").strip() else None
            )
            response_context = (
                opener.open(request, timeout=max(1.0, float(timeout)))
                if opener is not None
                else urlopen(request, timeout=max(1.0, float(timeout)))
            )
            with response_context as response:
                body = response.read(cls.MAX_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 200) or 200)
        except HTTPError as exc:
            if exc.code in {401, 403}:
                message = f"provider rejected the API key (HTTP {exc.code})"
            elif exc.code == 404:
                message = (
                    "provider API address does not expose /models "
                    "(HTTP 404)"
                )
            elif exc.code == 429:
                message = f"provider rate-limited the request (HTTP {exc.code})"
            else:
                message = f"provider returned HTTP {exc.code}"
            raise AgentProviderHealthError(
                message
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise AgentProviderHealthError(
                "provider connection failed; check the API address and network"
            ) from exc
        if len(body) > cls.MAX_RESPONSE_BYTES:
            raise AgentProviderHealthError("provider model response is too large")
        if status < 200 or status >= 300:
            raise AgentProviderHealthError(
                f"provider returned an unexpected HTTP status ({status})"
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentProviderHealthError(
                "provider returned an invalid model-list response"
            ) from exc
        if not isinstance(payload, Mapping):
            raise AgentProviderHealthError("provider model-list response is invalid")
        entries = payload.get("data")
        if not isinstance(entries, list):
            raise AgentProviderHealthError(
                "provider model-list response does not contain data"
            )
        model_ids = {
            str(item.get("id") or "").strip()
            for item in entries
            if isinstance(item, Mapping)
        }
        if model not in model_ids:
            raise AgentProviderHealthError(
                f"default model is not available: {model}"
            )
        return {
            "status": "ok",
            "provider_id": str(provider.get("provider_id") or ""),
            "protocol": protocol,
            "base_url": base_url,
            "default_model": model,
            "model_available": True,
        }


__all__ = ["AgentProviderHealth", "AgentProviderHealthError"]
