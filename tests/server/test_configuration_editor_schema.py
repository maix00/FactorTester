"""The editor projects registry metadata; it does not become an execution API."""
from copy import deepcopy
from uuid import uuid4

import pytest

from server.manager.services.test_authoring import TestAuthoringService as AuthoringService
from server.manager.services.test_authoring import TestAuthoringError as AuthoringError
from tools.testers.settings import backtest_setting_registry
from tools.testers.settings.json_schema import configuration_editor_contract


def test_registry_projection_preserves_each_registered_execution_field():
    contract = configuration_editor_contract()
    fields = contract["schema"]["properties"]["analyses"]["properties"]["backtest"]["properties"]["execution"]["properties"]["settings"]["properties"]
    app = backtest_setting_registry.get("group_test")
    expected = {key for key, setting in app.settings.items()
                if setting.execution_policy == "include" and not setting.adapter_managed}
    assert set(fields) == expected
    assert fields["split_count"]["default"] == app.settings["split_count"].default
    assert contract["schema"]["additionalProperties"] is True
    assert len({tuple(row["path"]) for row in contract["catalog"]}) == len(contract["catalog"])


def test_schema_is_metadata_only_independent_and_localized():
    first = configuration_editor_contract()
    second = configuration_editor_contract(locale="en")
    assert first["catalog"][0]["title"] != second["catalog"][0]["title"]
    expected = deepcopy(second)
    first["catalog"][0]["value"] = "changed"
    assert configuration_editor_contract(locale="en") == expected


def test_authenticated_authoring_dispatch_exposes_schema_without_workspace_reads():
    path = "/api/test-authoring/configuration-schema"
    assert AuthoringService.handles(path, "GET")
    assert not AuthoringService.handles(path, "PUT")
    value = AuthoringService().get(path, owner="alice", query={"locale": ["en"]}).payload
    assert value["success"] is True
    assert value["schema"]["properties"]["schema_version"]["const"] == 3


def test_suggested_defaults_are_copies_of_the_registered_values():
    contract = configuration_editor_contract()
    app = backtest_setting_registry.get("group_test")
    for item in contract["catalog"]:
        if item["analysis"] == "backtest":
            assert item["value"] == app.settings[item["key"]].default


def test_existing_save_api_preserves_extensions_owner_scope_and_revision():
    service = AuthoringService()
    owner = f"schema-editor-{uuid4().hex}"
    created = service.write("POST", "/api/test-authoring/workspaces", owner=owner,
                            payload={"title": "Schema editor test", "factors": []}).payload
    path = f'/api/test-authoring/workspaces/{created["workspace"]["workspace_id"]}/configuration'
    original = service.get(path, owner=owner).payload["configuration"]
    candidate = deepcopy(original["payload"])
    candidate["extension"] = {"unknown": [0, False, None]}
    saved = service.write("PUT", path, owner=owner, payload={
        "expected_revision": original["revision"], "payload": candidate,
    }).payload["configuration"]
    assert saved["payload"]["extension"] == candidate["extension"]
    assert saved["revision"] > original["revision"]
    with pytest.raises(AuthoringError) as conflict:
        service.write("PUT", path, owner=owner, payload={
            "expected_revision": original["revision"], "payload": candidate,
        })
    assert conflict.value.status == 409
    with pytest.raises(AuthoringError) as forbidden:
        service.get(path, owner=owner + "-other")
    assert forbidden.value.status == 404
