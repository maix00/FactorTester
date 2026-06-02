from __future__ import annotations

import importlib.util
from pathlib import Path

from tests._repo import repo_root


def _refresh_template_product_group_paths(template, groups):
    module_path = repo_root(Path(__file__)) / "server/modules/templates/snapshot_product_groups.py"
    spec = importlib.util.spec_from_file_location("_snapshot_product_groups_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.refresh_template_product_group_paths(template, groups)


def test_saved_product_group_submission_uses_latest_group_paths_on_load():
    template = {
        "snapshot": {
            "submissions": [{
                "product_group": "Metals",
                "paths": ["Old/Metals"],
                "selected_paths": ["Old/Metals"],
            }]
        }
    }
    groups = [{"name": "Metals", "paths": ["New/Metals", "-New/Metals/_products/RB.SHF"]}]

    refreshed = _refresh_template_product_group_paths(template, groups)

    submission = refreshed["snapshot"]["submissions"][0]
    assert submission["paths"] == ["New/Metals", "-New/Metals/_products/RB.SHF"]
    assert submission["selected_paths"] == ["New/Metals", "-New/Metals/_products/RB.SHF"]
    assert template["snapshot"]["submissions"][0]["paths"] == ["Old/Metals"]


def test_manual_submission_and_missing_group_keep_saved_path_snapshot():
    template = {
        "snapshot": {
            "submissions": [
                {"paths": ["Manual/Path"], "selected_paths": ["Manual/Path"]},
                {"product_group": "Removed", "paths": ["Saved/Path"], "selected_paths": ["Saved/Path"]},
            ]
        }
    }

    refreshed = _refresh_template_product_group_paths(template, [{"name": "Other", "paths": ["New/Path"]}])

    assert refreshed["snapshot"]["submissions"][0]["paths"] == ["Manual/Path"]
    assert refreshed["snapshot"]["submissions"][1]["paths"] == ["Saved/Path"]
