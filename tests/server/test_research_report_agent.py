import json
from server.jobs.storage.research_report_agent import agent_manifest, agent_markdown, chapter_attachment_path


class Store:
    def get_attachment(self, doc_id, name):
        return json.dumps({"title": "Chapter", "components": [
            {"component_id": "c1", "kind": "paragraph", "title": "", "body": "hello"},
        ]}).encode()


def test_manifest_and_markdown_are_agent_readable():
    document = {"_id": "research-report:p1", "publication_id": "p1", "title": "T",
                "attachments": {chapter_attachment_path("chapter-1"): {"name": "x.json", "content_type": "application/json"}}}
    projection = {"chapters": [{"component_id": "chapter-1", "title": "One"}]}
    manifest = agent_manifest(document, projection)
    assert manifest["report"]["title"] == "T"
    assert manifest["entrypoints"]["markdown"].endswith("/agent.md")
    markdown = agent_markdown(Store(), document, projection)
    assert "hello" in markdown
