"""Supported Profile Agent runtimes and Provider wire protocols."""

from __future__ import annotations

from dataclasses import dataclass


class AgentRuntimeCapabilityError(ValueError):
    """A runtime or protocol cannot be represented by the Manager."""


@dataclass(frozen=True)
class AgentRuntimeCapability:
    runtime: str
    protocols: frozenset[str]
    executable_label: str
    default_binary: str


CAPABILITIES = {
    "codex": AgentRuntimeCapability(
        runtime="codex",
        protocols=frozenset({
            "anthropic_messages",
            "openai_chat",
            "openai_responses",
        }),
        executable_label="Codex",
        default_binary="codex",
    ),
}

PROTOCOL_DETAILS = {
    "openai_responses": {
        "label": "OpenAI Responses API",
        "transport": "direct",
        "transport_label": "直接连接",
    },
    "openai_chat": {
        "label": "OpenAI Chat Completions API",
        "transport": "cc_switch",
        "transport_label": "CC Switch 转换",
    },
    "anthropic_messages": {
        "label": "Anthropic Messages API",
        "transport": "cc_switch",
        "transport_label": "CC Switch 转换",
    },
}

PROTOCOL_ALIASES = {
    "openai_compatible": "openai_responses",
}

NETWORK_ROUTE_DETAILS = [
    {"network_route": "direct", "label": "直接连接"},
    {
        "network_route": "manager_proxy",
        "label": "使用 Manager 网络代理",
    },
]


def normalize_runtime(value: object) -> str:
    runtime = str(value or "").strip() or "codex"
    if runtime not in CAPABILITIES:
        raise AgentRuntimeCapabilityError("Agent runtime is unsupported")
    return runtime


def normalize_protocol(value: object) -> str:
    protocol = str(value or "").strip()
    protocol = PROTOCOL_ALIASES.get(protocol, protocol)
    if protocol not in {
        protocol
        for capability in CAPABILITIES.values()
        for protocol in capability.protocols
    }:
        raise AgentRuntimeCapabilityError("provider protocol is unsupported")
    return protocol


def validate_runtime_protocol(runtime: object, protocol: object) -> tuple[str, str]:
    normalized_runtime = normalize_runtime(runtime)
    normalized_protocol = normalize_protocol(protocol)
    if normalized_protocol not in CAPABILITIES[normalized_runtime].protocols:
        raise AgentRuntimeCapabilityError(
            "Agent runtime and provider protocol are incompatible"
        )
    return normalized_runtime, normalized_protocol


def public_capabilities() -> list[dict[str, object]]:
    return [
        {
            "runtime": capability.runtime,
            "protocols": sorted(capability.protocols),
            "protocol_details": [
                {"protocol": protocol, **PROTOCOL_DETAILS[protocol]}
                for protocol in sorted(capability.protocols)
            ],
            "executable_label": capability.executable_label,
            "network_route_details": NETWORK_ROUTE_DETAILS,
        }
        for capability in CAPABILITIES.values()
    ]


__all__ = [
    "AgentRuntimeCapability",
    "AgentRuntimeCapabilityError",
    "CAPABILITIES",
    "PROTOCOL_DETAILS",
    "NETWORK_ROUTE_DETAILS",
    "normalize_protocol",
    "normalize_runtime",
    "public_capabilities",
    "validate_runtime_protocol",
]
