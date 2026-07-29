from tools.cli.client import FactorTesterClient


class _Session:
    def get(self, path, *, query=None):
        assert path == "/api/report-references/resolve"
        assert query == {"kind": "product", "target": "SI.GFE"}
        return {
            "success": True,
            "reference": {
                "kind": "product",
                "target_ref": (
                    "Product/Futures/CNFutures/_products/SI.GFE"
                ),
                "label": "工业硅",
            },
        }


def test_client_resolves_report_reference_through_server():
    client = FactorTesterClient(_Session())

    reference = client.resolve_report_reference(
        kind="product",
        target="SI.GFE",
    )

    assert reference["label"] == "工业硅"
