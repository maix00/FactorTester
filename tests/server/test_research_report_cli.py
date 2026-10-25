from tools.cli.client import FactorTesterClient


class Session:
    def __init__(self): self.posted = None
    def get(self, path): return {"success": True, "publication_id": "p1"}
    def post(self, path, payload):
        self.posted = (path, payload); return {"success": True, "rev": "2-b"}


def test_client_applies_report_operation():
    session = Session(); client = FactorTesterClient(session)
    result = client.apply_research_report_operation(
        "p1", base_rev="1-a",
        operation={"op": "move_chapter", "chapter_id": "a"},
    )
    assert result["rev"] == "2-b"
    assert session.posted[1]["base_rev"] == "1-a"
