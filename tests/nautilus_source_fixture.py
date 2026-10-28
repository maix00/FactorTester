"""Source-owned LocalCNFutures member for isolated NT conversion tests."""

from __future__ import annotations

from sources.LocalCNFutures.nautilus_adapter import CONTRACT_MIN1
from server.services.nautilus_bridge.source_registry import (
    ResolvedSource, from_server_sources,
)
from tools.data.source_catalog import data_source_declarations


def resolved_contract_minute_source() -> ResolvedSource:
    registry = from_server_sources()
    capability = next(c for c in registry.capabilities()
                      if c.member_key == CONTRACT_MIN1.member_key)
    member = next(m for d in data_source_declarations() for m in d.members
                  if m.key == CONTRACT_MIN1.member_key)
    return ResolvedSource(capability, CONTRACT_MIN1,
                          member.execution_provider, member)
