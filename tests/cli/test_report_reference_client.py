from tools.cli.client import FactorTesterClient


class _Session:
    def get(self, path, *, query=None):
        assert path == "/api/report-references/validate"
        assert query == {
            "kind": "product",
            "target_ref": "Product/Futures/CNFutures/_products/SI.GFE",
        }
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


def test_client_validates_an_agent_authored_report_reference():
    client = FactorTesterClient(_Session())

    reference = client.validate_report_reference(
        kind="product",
        target_ref="Product/Futures/CNFutures/_products/SI.GFE",
    )

    assert reference["label"] == "工业硅"
