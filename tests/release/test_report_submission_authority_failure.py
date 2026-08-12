from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from tools.cli.commands.research_report_submission import (
    begin_component_submission,
)
from tools.cli.commands.research_report_submission_errors import (
    SequencedSubmissionError,
)
from tools.cli.release.research_reporting.authoring.submission_pending import (
    load_pending,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    initialize_tree,
)
from tools.cli.release.research_reporting.references import (
    preflight as preflight_module,
)


def test_authority_connection_failure_becomes_a_persisted_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    scope = SimpleNamespace(
        package_root=package,
        branch_id="main",
        client_root=tmp_path / "client",
        profile_id="maxa",
        profile={},
    )
    monkeypatch.setattr(
        preflight_module,
        "validate_declared_reference",
        lambda **_kwargs: (_ for _ in ()).throw(
            URLError("authority unavailable")
        ),
    )
    component = {
        "component_id": "product-finding",
        "kind": "entry",
        "title": "品种",
        "body": (
            "[工业硅](factortester://product/"
            "Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)"
        ),
        "content": None,
        "display_kind": "",
    }

    with pytest.raises(SequencedSubmissionError):
        begin_component_submission(
            scope=scope,
            requested_sequence=None,
            component=component,
            as_json=True,
        )

    pending = load_pending(created["paths"])
    assert pending is not None
    assert pending["submission_sequence"] == 1
    assert pending["diagnostics"][0]["code"] == "report.reference.authority"
    assert "authority unavailable" in pending["diagnostics"][0]["message"]
