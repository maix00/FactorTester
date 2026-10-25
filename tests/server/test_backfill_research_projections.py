from scripts.migrations.backfill_research_report_projections import link


def test_projection_link_is_content_addressed(tmp_path):
    path = tmp_path / "mirror.json"; path.write_text("{}")
    meta = link(path, b"{}")
    assert meta["name"].endswith(".json")
    assert len(meta["name"]) == 64 + 5
