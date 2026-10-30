"""Keycloak-authenticated execution node operations on existing Jobs."""
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.identity.service_access import authenticate_service
from server.manager.http.responses import json_response
from server.manager.http.request_security import read_json_object


class ExecutionNodeRoutesMixin:
    def _dispatch_execution_node(self, path):
        operation = {
            "/api/federation/execution/register": "register",
            "/api/federation/execution/job": "operation",
            "/api/federation/execution/result-file": "report_file",
            "/api/federation/execution/report": "publish_report",
        }.get(path)
        if operation is None:
            return False
        self._execution_node_operation(operation)
        return True

    def _execution_node_operation(self, operation):
        try:
            body, payload = read_json_object(self, 1024*1024)
            identity = authenticate_service(self, required_scope="tr:execution:node")
            if not identity.node_id:
                raise PermissionError("token is not bound to an execution node")
            repository = getattr(self.state, "job_repository", None) or JobRepository()
            service = ExecutionNodeService(repository, manager_id=self.state.server_id)
            value = getattr(service, operation)(identity.node_id, payload)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return
        json_response(self, {"success": True, **value})
