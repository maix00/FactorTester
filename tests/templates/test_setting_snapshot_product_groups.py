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


def test_saved_product_group_submission_keeps_only_group_id_on_load():
    template = {
        "snapshot": {
            "group_settings": {
                "groups": [{
                    "id": "g1",
                    "product_path_selection": {
                        "product_group_template_id": "pg-metals",
                        "product_group": "Metals",
                        "paths": ["Old/Metals"],
                        "selected_paths": ["Old/Metals"],
                    },
                }]
            }
        }
    }
    groups = [{"id": "pg-metals", "name": "Metals", "paths": ["New/Metals", "-New/Metals/_products/RB.SHF"]}]

    refreshed = _refresh_template_product_group_paths(template, groups)

    submission = refreshed["snapshot"]["group_settings"]["groups"][0]["product_path_selection"]
    assert submission == {"product_path_selection_id": "pg-metals"}
    assert template["snapshot"]["group_settings"]["groups"][0]["product_path_selection"]["paths"] == ["Old/Metals"]


def test_product_group_template_builds_matching_product_path_selection(monkeypatch):
    from server.modules.products.product_group_store import product_group_to_path_selection

    monkeypatch.setattr(
        "tools.products.product_path_selection.resolve_products_from_paths",
        lambda paths: (list(paths), ["CU.SHF", "AL.SHF"]),
    )

    selection = product_group_to_path_selection(
        {"id": "pg-metals", "name": "Metals", "paths": ["New/Metals"]},
        selection_id="metals-selection",
        page_uuid="page-a",
    )

    assert selection.selection_id == "metals-selection"
    assert selection.product_group == "Metals"
    assert selection.product_group_template_id == "pg-metals"
    assert selection.source_type == "user_product_group_template"
    assert selection.source_key == "pg-metals"
    assert selection.selected_paths == ["New/Metals"]
    assert selection.products == ["CU.SHF", "AL.SHF"]


def test_manual_submission_and_missing_group_keep_saved_path_snapshot():
    template = {
        "snapshot": {
            "execution": {"settings": {
                "product_path_selection": {"paths": ["Manual/Path"], "selected_paths": ["Manual/Path"]},
            }},
            "group_settings": {
                "groups": [{
                    "product_path_selection": {"product_group": "Removed", "paths": ["Saved/Path"], "selected_paths": ["Saved/Path"]},
                }]
            },
        }
    }

    refreshed = _refresh_template_product_group_paths(template, [{"name": "Other", "paths": ["New/Path"]}])

    assert refreshed["snapshot"]["execution"]["settings"]["product_path_selection"]["paths"] == ["Manual/Path"]
    assert refreshed["snapshot"]["group_settings"]["groups"][0]["product_path_selection"]["paths"] == ["Saved/Path"]
