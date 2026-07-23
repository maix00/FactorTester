from __future__ import annotations

import json

import settings as Settings
from server.services.research_graph.packet_budget import (
    configure_runtime_packet_budget_profile,
    graph_packet_budget,
    reset_runtime_packet_budget_cache,
)
from cli_anything.factortester_research.core.successor_graph import (
    build_successor_graph,
)


def test_configured_budget_profile_is_versioned_outside_graph(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    reset_runtime_packet_budget_cache()
    graph = build_successor_graph()
    graph_hash = graph["content_hash"]

    first = configure_runtime_packet_budget_profile(
        ceiling_bytes=7000,
        actor="alice",
        provider_id="provider-a",
        model_id="model-a",
        tokenizer_id="tokenizer-a",
        tokenizer_revision="revision-1",
    )
    second = configure_runtime_packet_budget_profile(
        ceiling_bytes=8000,
        actor="alice",
        provider_id="provider-a",
        model_id="model-a",
        tokenizer_id="tokenizer-a",
        tokenizer_revision="revision-1",
    )
    active = graph_packet_budget(graph)
    store = json.loads(
        (tmp_path / "research-runtime-budget-profiles.json").read_text()
    )

    assert first["base_profile_hash"] != second["base_profile_hash"]
    assert active["ceiling_bytes"] == 8000
    assert active["base_profile_hash"] == second["base_profile_hash"]
    assert len(store["profiles"]) == 2
    assert store["active_profile_hash"] == second["base_profile_hash"]
    assert graph["content_hash"] == graph_hash
