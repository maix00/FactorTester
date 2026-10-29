import json

from scripts.migrations.keycloak_directory_compare import (
    compare_directories,
    main,
)


def _snapshot(*, key="users", username="alice", role="user", active_marker=False):
    account = {
        "username": username,
        "alias": "Alice",
        "role": role,
        "is_admin": False,
        "is_developer": False,
        "organization_id": "org-1",
        "organization_name": "Org One",
        "level_id": "root-1",
        "parent_username": "",
    }
    if active_marker:
        account["active"] = True
    return {
        key: [account],
        "organizations": [{"id": "org-1", "name": "Org One", "description": ""}],
        "levels": [{
            "id": "root-1", "organization_id": "org-1", "name": "Root",
            "parent_level_id": "", "manager_username": "",
        }],
    }


def test_matching_manager_directories_produce_pii_free_cutover_gate():
    report = compare_directories(
        _snapshot(key="accounts"),
        _snapshot(key="users", active_marker=True),
    )

    assert report["legacy_directory_preflight_passes"] is True
    assert report["users"]["exact_identity_set_match"] is True
    assert report["users"]["account_field_differences"] == {}
    assert report["users"]["credential_material_exported"] is False
    assert "alice" not in json.dumps(report).lower()


def test_case_change_and_role_mismatch_fail_closed_without_emitting_usernames(
    tmp_path, capsys,
):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(json.dumps(_snapshot(username="Alice")))
    right.write_text(json.dumps(_snapshot(username="alice", role="developer")))

    assert main(["--left", str(left), "--right", str(right)]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)

    assert report["legacy_directory_preflight_passes"] is False
    assert report["users"]["casefold_matched_count"] == 1
    assert report["users"]["username_case_difference_count"] == 1
    assert report["users"]["account_field_differences"] == {"role": 1}
    assert "Alice" not in output
    assert "alice" not in output


def test_same_but_invalid_hierarchy_does_not_pass_cutover_gate():
    left = _snapshot()
    right = _snapshot(active_marker=True)
    left["levels"][0]["parent_level_id"] = "missing-parent"
    right["levels"][0]["parent_level_id"] = "missing-parent"

    report = compare_directories(left, right)

    assert report["levels"]["field_differences"] == {}
    assert report["directory_integrity"]["left"]["invalid_hierarchy_rows"] > 0
    assert report["directory_integrity"]["right"]["invalid_hierarchy_rows"] > 0
    assert report["legacy_directory_preflight_passes"] is False


def test_matching_but_unmapped_or_unprovisioned_roles_block_cutover():
    left = _snapshot()
    right = _snapshot(active_marker=True)
    for snapshot in (left, right):
        snapshot["users"][0]["role"] = "level_admin"

    report = compare_directories(left, right)

    assert report["users"]["account_field_differences"] == {}
    assert report["legacy_role_mapping_plan"]["left"][
        "scoped_authorization_not_provisioned_rows"
    ] == 1
    assert report["legacy_role_mapping_plan"]["right"][
        "scoped_authorization_not_provisioned_rows"
    ] == 1
    assert report["legacy_directory_preflight_passes"] is False
