import base64
import hashlib

from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary


def test_public_research_asset_is_stored_and_read_with_visibility(tmp_path):
    raw = b"test image bytes"
    asset_id = "asset-12345678"
    digest = hashlib.sha256(raw).hexdigest()
    projection = {
        "schema_version": 2,
        "report_id": "report-1",
        "title": "Report",
        "language": "zh-Hans",
        "generation": 1,
        "components": [],
        "assets": [{
            "asset_id": asset_id,
            "media_type": "image/png",
            "filename": "figure.png",
            "content_hash": digest,
            "caption": "Figure",
            "alt_text": "",
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "local_resources": [],
        "projection_hash": "hash",
    }
    library = PublicResearchLibrary(tmp_path)
    result = library.sync({
        "report_id": "report-1", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-1", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )

    assert library.asset(result["publication_id"], asset_id, None)[:2] == (raw, "image/png")
