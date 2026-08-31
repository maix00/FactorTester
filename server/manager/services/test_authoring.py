"""Manager-owned test authoring APIs.

The test editor is a client capability: schemas, editable workspaces,
templates, categories, and output declarations must remain available even
when no execution service is running.  Only Run preview/submission and Job
actions cross a selected service port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


@dataclass(frozen=True)
class TestAuthoringResponse:
    payload: dict[str, Any]
    status: int = 200


class TestAuthoringError(RuntimeError):
    def __init__(self, message: str, status: int = 400, **details: Any) -> None:
        super().__init__(message)
        self.status = int(status)
        self.details = details


class TestAuthoringService:
    """Serve authoring state directly from the shared local data store."""

    _WORKSPACE_RE = re.compile(r"/api/test-authoring/workspaces/([^/]{1,128})")
    _CONFIG_RE = re.compile(
        r"/api/test-authoring/workspaces/([^/]{1,128})/configuration"
    )
    _SNAPSHOT_RE = re.compile(
        r"/api/test-authoring/workspaces/([^/]{1,128})/configuration-snapshots"
    )
    _SAVE_TEMPLATE_RE = re.compile(
        r"/api/test-authoring/workspaces/([^/]{1,128})/configuration/templates"
    )
    _LOAD_TEMPLATE_RE = re.compile(
        r"/api/test-authoring/workspaces/([^/]{1,128})/configuration/load-template"
    )
    _TEMPLATE_RE = re.compile(r"/api/test-authoring/configuration-templates/([^/]{1,128})")
    _SETTINGS_RE = re.compile(r"/api/test-authoring/modules/([^/]{1,128})")
    _SETTINGS_SUMMARY_RE = re.compile(
        r"/api/test-authoring/modules/([^/]{1,128})/summary"
    )
    _SETTINGS_TAB_RE = re.compile(
        r"/api/test-authoring/modules/([^/]{1,128})/tabs/([^/]{1,128})"
    )

    @classmethod
    def handles(cls, path: str, method: str) -> bool:
        if method == "GET":
            return bool(
                path in {
                    "/api/test-authoring/workspaces",
                    "/api/test-authoring/workspace-summaries",
                    "/api/test-authoring/configuration-templates",
                    "/api/product-library/data-source-categories",
                    "/api/jobs/artifact-capabilities",
                    "/api/test-authoring/modules",
                }
                or cls._SETTINGS_RE.fullmatch(path)
                or cls._SETTINGS_SUMMARY_RE.fullmatch(path)
                or cls._SETTINGS_TAB_RE.fullmatch(path)
                or cls._WORKSPACE_RE.fullmatch(path)
                or cls._CONFIG_RE.fullmatch(path)
                or cls._SNAPSHOT_RE.fullmatch(path)
            )
        if method == "POST":
            return bool(
                path == "/api/test-authoring/workspaces"
                or cls._SAVE_TEMPLATE_RE.fullmatch(path)
                or cls._LOAD_TEMPLATE_RE.fullmatch(path)
                or cls._SNAPSHOT_RE.fullmatch(path)
            )
        if method == "PUT":
            return bool(
                cls._CONFIG_RE.fullmatch(path)
                or cls._TEMPLATE_RE.fullmatch(path)
            )
        return bool(method == "DELETE" and (
            cls._TEMPLATE_RE.fullmatch(path) or cls._WORKSPACE_RE.fullmatch(path)
        ))

    @staticmethod
    def prepare_run_context(
        payload: dict[str, Any],
        *,
        owner: str,
        source_free: bool = False,
        storage_server_id: str = "",
        source_collector=None,
        authorized_factor_owners: object = (),
    ) -> dict[str, Any]:
        """Freeze local authoring state into a portable execution context."""
        from server.modules.single_factor_test.research_jobs import (
            prepare_manager_run_context,
        )
        from server.services.factor_registry import (
            authorized_factor_source_owners,
        )
        from server.services.research_run_context import RunRequestError

        try:
            with authorized_factor_source_owners(authorized_factor_owners):
                return prepare_manager_run_context(
                    payload,
                    owner=owner,
                    source_free=source_free,
                    storage_server_id=storage_server_id,
                    source_collector=source_collector,
                )
        except RunRequestError as exc:
            raise TestAuthoringError(
                str(exc), exc.status_code, **exc.details,
            ) from exc

    def get(
        self,
        path: str,
        *,
        owner: str,
        query: dict[str, list[str]] | None = None,
    ) -> TestAuthoringResponse:
        if path == "/api/test-authoring/modules":
            from server.modules.single_factor_test.backtest_settings import (
                _navigation_children,
            )
            from tools.testers.home import HomeModuleRegistry

            values = query or {}
            parent = str(values.get("parent", [""])[0] or "").strip()
            try:
                modules = _navigation_children(HomeModuleRegistry(), parent)
            except KeyError as exc:
                raise TestAuthoringError(str(exc), 404) from exc
            return TestAuthoringResponse({
                "success": True,
                "parent": parent or None,
                "modules": modules,
            })
        if match := self._SETTINGS_SUMMARY_RE.fullmatch(path):
            return TestAuthoringResponse(self._settings_manifest(
                unquote(match.group(1)), mode="summary",
            ))
        if match := self._SETTINGS_TAB_RE.fullmatch(path):
            return TestAuthoringResponse(self._settings_tab_manifest(
                unquote(match.group(1)), unquote(match.group(2)),
            ))
        if match := self._SETTINGS_RE.fullmatch(path):
            return TestAuthoringResponse(self._settings_manifest(
                unquote(match.group(1)),
            ))
        if path == "/api/product-library/data-source-categories":
            from server.modules.single_factor_test.category_routes import (
                list_data_source_categories,
            )
            return TestAuthoringResponse({
                "success": True,
                "categories": list_data_source_categories(),
            })
        if path == "/api/jobs/artifact-capabilities":
            from server.jobs.report_outputs.definitions import output_capabilities
            return TestAuthoringResponse({
                "success": True,
                "schema_version": 1,
                "outputs": output_capabilities(),
            })
        if path == "/api/test-authoring/workspaces":
            from server.services import research_workspaces
            return TestAuthoringResponse({
                "success": True,
                "workspaces": research_workspaces.list_workspaces(owner=owner),
            })
        if path == "/api/test-authoring/workspace-summaries":
            from server.services import research_workspaces
            return TestAuthoringResponse({
                "success": True,
                "workspaces": research_workspaces.list_workspace_summaries(owner=owner),
            })
        if path == "/api/test-authoring/configuration-templates":
            from server.services import research_configurations
            return TestAuthoringResponse({
                "success": True,
                "templates": research_configurations.list_templates(owner=owner),
            })
        if match := self._CONFIG_RE.fullmatch(path):
            from server.services import research_configurations
            value = research_configurations.load_workspace_configuration(
                workspace_id=unquote(match.group(1)), owner=owner,
            )
            if value is None:
                raise TestAuthoringError(
                    "workspace configuration not found", 404,
                )
            return TestAuthoringResponse({
                "success": True, "configuration": value,
            })
        if match := self._SNAPSHOT_RE.fullmatch(path):
            from server.services import research_configuration_snapshots
            return TestAuthoringResponse({
                "success": True,
                "snapshots": research_configuration_snapshots.list_snapshots(
                    owner=owner,
                    workspace_id=unquote(match.group(1)),
                ),
            })
        if match := self._WORKSPACE_RE.fullmatch(path):
            from server.services import research_workspaces
            value = research_workspaces.load_workspace(
                workspace_id=unquote(match.group(1)), owner=owner,
            )
            if value is None:
                raise TestAuthoringError("workspace not found", 404)
            return TestAuthoringResponse({"success": True, "workspace": value})
        raise TestAuthoringError("test authoring route not found", 404)

    def write(
        self, method: str, path: str, *, owner: str, payload: dict[str, Any],
    ) -> TestAuthoringResponse:
        from server.services import research_configurations, research_workspaces

        if method == "DELETE" and (match := self._WORKSPACE_RE.fullmatch(path)):
            value = research_workspaces.delete_draft_workspace(
                workspace_id=unquote(match.group(1)), owner=owner,
            )
            if value is None:
                raise TestAuthoringError("workspace not found", 404)
            return TestAuthoringResponse({"success": True, **value})

        if method == "POST" and path == "/api/test-authoring/workspaces":
            factors = self._object_list(payload, "factors")
            workspace = research_workspaces.create_workspace(
                owner=owner,
                title=str(payload.get("title") or "Factor test").strip(),
                factors=factors,
            )
            return TestAuthoringResponse({
                "success": True, "workspace": workspace,
            }, 201)
        if match := self._SNAPSHOT_RE.fullmatch(path):
            from server.services import research_configuration_snapshots
            workspace_id = unquote(match.group(1))
            try:
                source_revision = self._required_int(
                    payload, "source_configuration_revision",
                )
                value = research_configuration_snapshots.create_snapshot(
                    owner=owner,
                    workspace_id=workspace_id,
                    source_workspace_id=str(
                        payload.get("source_workspace_id") or workspace_id
                    ),
                    source_configuration_id=str(
                        payload.get("source_configuration_id") or ""
                    ),
                    source_configuration_revision=source_revision,
                    name=str(payload.get("name") or ""),
                )
            except KeyError as exc:
                raise TestAuthoringError(str(exc), 404) from exc
            except ValueError as exc:
                raise TestAuthoringError(str(exc), 409) from exc
            return TestAuthoringResponse({
                "success": True, "snapshot": value,
            }, 201)
        if match := self._CONFIG_RE.fullmatch(path):
            if method == "PUT":
                revision = self._required_int(payload, "expected_revision")
                try:
                    value = research_configurations.update_workspace_configuration(
                        workspace_id=unquote(match.group(1)), owner=owner,
                        expected_revision=revision, payload=payload.get("payload"),
                    )
                except research_configurations.ConfigurationRevisionConflict as exc:
                    raise TestAuthoringError(
                        str(exc), 409, current_revision=exc.current_revision,
                    ) from exc
                except KeyError as exc:
                    raise TestAuthoringError(str(exc), 404) from exc
                return TestAuthoringResponse({
                    "success": True, "configuration": value,
                })
        if match := self._SAVE_TEMPLATE_RE.fullmatch(path):
            name = str(payload.get("name") or "").strip()
            if not name:
                raise TestAuthoringError("template name is required")
            try:
                value = research_configurations.save_template(
                    workspace_id=unquote(match.group(1)), owner=owner, name=name,
                )
            except KeyError as exc:
                raise TestAuthoringError(str(exc), 404) from exc
            return TestAuthoringResponse({
                "success": True, "template": value,
            }, 201)
        if match := self._LOAD_TEMPLATE_RE.fullmatch(path):
            revision = self._required_int(payload, "expected_revision")
            try:
                value = research_configurations.load_template_into_workspace(
                    configuration_id=str(payload.get("configuration_id") or ""),
                    workspace_id=unquote(match.group(1)), owner=owner,
                    expected_revision=revision,
                )
            except research_configurations.ConfigurationRevisionConflict as exc:
                raise TestAuthoringError(
                    str(exc), 409, current_revision=exc.current_revision,
                ) from exc
            except KeyError as exc:
                raise TestAuthoringError(str(exc), 404) from exc
            return TestAuthoringResponse({
                "success": True, "configuration": value,
            })
        if match := self._TEMPLATE_RE.fullmatch(path):
            configuration_id = unquote(match.group(1))
            if method == "PUT":
                workspace_id = str(payload.get("workspace_id") or "").strip()
                if not workspace_id:
                    raise TestAuthoringError("workspace_id is required")
                try:
                    value = research_configurations.overwrite_template_from_workspace(
                        configuration_id=configuration_id,
                        workspace_id=workspace_id, owner=owner,
                    )
                except KeyError as exc:
                    raise TestAuthoringError(str(exc), 404) from exc
                return TestAuthoringResponse({
                    "success": True, "template": value,
                })
            if method == "DELETE":
                if not research_configurations.delete_template(
                    configuration_id=configuration_id, owner=owner,
                ):
                    raise TestAuthoringError("template not found", 404)
                return TestAuthoringResponse({
                    "success": True, "configuration_id": configuration_id,
                })
        raise TestAuthoringError("test authoring route not found", 404)

    @staticmethod
    def _settings_manifest(
        application: str, *, mode: str = "full",
    ) -> dict[str, Any]:
        from tools.testers.backtest.modules.registry import BacktestModuleRegistry
        from tools.testers.home import HomeModuleRegistry
        from tools.testers.settings import backtest_setting_registry

        try:
            app = backtest_setting_registry.get(application)
            manifest = app.summary() if mode == "summary" else app.manifest()
        except KeyError as exc:
            raise TestAuthoringError(str(exc), 404) from exc
        module = HomeModuleRegistry().find(application)
        registry = (
            module.sub_registry
            if module is not None
            and isinstance(module.sub_registry, BacktestModuleRegistry)
            else BacktestModuleRegistry()
        )
        manifest["executable_modules"] = registry.module_manifest()
        if application == "single_factor_page":
            manifest["shared_global_default_keys"] = (
                backtest_setting_registry.shared_global_default_keys((
                    "factor_evaluation", "ic_test", "group_test",
                ))
            )
        return {"success": True, **manifest}

    @staticmethod
    def _settings_tab_manifest(application: str, tab_key: str) -> dict[str, Any]:
        from tools.testers.backtest.modules.registry import BacktestModuleRegistry
        from tools.testers.home import HomeModuleRegistry
        from tools.testers.settings import backtest_setting_registry

        try:
            manifest = backtest_setting_registry.get(application).tab_manifest(tab_key)
        except KeyError as exc:
            raise TestAuthoringError(str(exc), 404) from exc
        module = HomeModuleRegistry().find(application)
        registry = (
            module.sub_registry
            if module is not None
            and isinstance(module.sub_registry, BacktestModuleRegistry)
            else BacktestModuleRegistry()
        )
        manifest["executable_modules"] = registry.module_manifest()
        return {"success": True, **manifest}

    @staticmethod
    def _required_int(payload: dict[str, Any], key: str) -> int:
        try:
            return int(payload.get(key))
        except (TypeError, ValueError) as exc:
            raise TestAuthoringError(f"{key} is required") from exc

    @staticmethod
    def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = payload.get(key) or []
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise TestAuthoringError(f"{key} must be an array of objects")
        return value
