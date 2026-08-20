"""Resolve one Agent Provider's explicit network route."""

from __future__ import annotations

from collections.abc import Callable, Mapping


class AgentProviderProxyUnavailable(RuntimeError):
    """A Provider requires the Manager proxy, but it is not available."""

    code = "proxy_unavailable"


def resolve_provider_proxy(
    provider: Mapping[str, object],
    proxy_url_provider: Callable[[], str] | None,
) -> str:
    """Return the required proxy URL without silently changing routes."""
    if str(provider.get("network_route") or "direct") != "manager_proxy":
        return ""
    proxy_url = ""
    if proxy_url_provider is not None:
        try:
            proxy_url = str(proxy_url_provider() or "").strip()
        except Exception:
            proxy_url = ""
    if not proxy_url:
        raise AgentProviderProxyUnavailable(
            "Manager network proxy is unavailable"
        )
    return proxy_url


__all__ = ["AgentProviderProxyUnavailable", "resolve_provider_proxy"]
