"""Signed execution-node control over existing node enrollment/challenges."""
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.manager.http.federation.node_auth import authenticated_node
from server.manager.http.responses import json_response


class ExecutionNodeRoutesMixin:
    def _execution_node_operation(self, operation):
        try:
            body, payload = self._node_json_body(1024*1024)
            identity = authenticated_node(self, method="POST", body=body)
            repository = getattr(self.state, "job_repository", None) or JobRepository()
            service = ExecutionNodeService(repository, manager_id=self.state.server_id)
            value = getattr(service, operation)(identity.node_id, payload)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return
        json_response(self, {"success": True, **value})
