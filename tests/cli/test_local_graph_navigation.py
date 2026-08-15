from __future__ import annotations

from pathlib import Path

from tools.cli.local_graph_navigation import evaluate_next, load_graph_document


def test_local_graph_loader_accepts_yaml(tmp_path: Path) -> None:
    graph_file = tmp_path / "graph.yaml"
    graph_file.write_text(
        """
graph_id: factor-research
version: 3
nodes:
  - node_id: entry
    kind: entry
edges:
  - edge_id: entry__next
    from_node: entry
    to_node: next
""".lstrip(),
        encoding="utf-8",
    )

    graph = load_graph_document(graph_file)
    result = evaluate_next(graph, current_node="entry")

    assert result["graph"] == "factor-research@v3"
    assert result["recommended_edge_ids"] == ["entry__next"]
    assert result["server_decides_next"] is False
