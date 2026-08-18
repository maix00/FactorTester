"""Authenticated HTTP routes for client-owned local-run projections."""

from __future__ import annotations

import re
from urllib.parse import parse_qs

from server.manager.http.responses import json_response


class ClientLocalRunRoutesMixin:
    """Keep local-run synchronization and artifact promotion in one seam."""

    def _post_local_run_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/local-runs/sync":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                payload = self._json_body(4 * 1024 * 1024)
                projection = self.state.local_run_projection.upsert(
                    str(session["username"]), payload,
                )
            except (TypeError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(self, {
                "success": True,
                "local_run": projection["job"],
                "task_detail": projection["task_detail"],
                "raw_artifacts_remote": False,
            })
            return True

        if parsed.path == "/api/client/local-runs/artifacts/access":
            return self._post_local_artifact_access()

        if parsed.path == "/api/client/local-runs/artifacts/complete":
            return self._post_local_artifact_complete()

        return False

    def _post_local_artifact_access(self) -> bool:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        try:
            payload = self._json_body(64 * 1024)
            job_id = str(payload.get("local_job_id") or "").strip()
            name = str(payload.get("name") or "").strip()
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise ValueError("local artifact name is invalid")
            projection = self.state.local_run_projection.get(
                str(session["username"]), job_id,
            )
            if projection is None:
                raise KeyError("local run was not found")
            artifact = _artifact(projection, name)
            expected_size = int(payload.get("size_bytes"))
            expected_sha256 = str(
                payload.get("content_hash") or ""
            ).strip().lower().removeprefix("sha256:")
            if expected_size != int(artifact.get("size_bytes") or 0):
                raise ValueError("local artifact size does not match projection")
            if expected_sha256 != str(
                artifact.get("content_hash") or ""
            ).strip().lower():
                raise ValueError("local artifact hash does not match projection")
            access = self._rewrite_client_data_access(
                self.state.prepare_submission_upload(
                    principal=str(session["username"]),
                    storage_server_id=self.state.server_id,
                    job_id=job_id,
                    name=name,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    idempotency_key=str(
                        self.headers.get("Idempotency-Key")
                        or f"local-run-upload:{job_id}:{name}:{expected_sha256}"
                    ),
                )
            )
        except KeyError as exc:
            json_response(self, {"success": False, "error": str(exc).strip("'")}, 404)
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, {
            "success": True,
            "access": access,
            "object": {
                "local_job_id": job_id,
                "name": name,
                "size_bytes": expected_size,
                "content_hash": expected_sha256,
            },
        }, 201)
        return True

    def _post_local_artifact_complete(self) -> bool:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        try:
            payload = self._json_body(64 * 1024)
            job_id = str(payload.get("local_job_id") or "").strip()
            name = str(payload.get("name") or "").strip()
            transfer_id = str(payload.get("transfer_id") or "").strip()
            if not job_id or not name or not transfer_id:
                raise ValueError("local artifact completion fields are required")
            projection = self.state.local_run_projection.get(
                str(session["username"]), job_id,
            )
            if projection is None:
                raise KeyError("local run was not found")
            artifact = _artifact(projection, name)
            self.state.require_completed_submission_upload(
                transfer_id,
                principal=str(session["username"]),
                job_id=job_id,
                artifact_name=name,
                expected_size=int(artifact.get("size_bytes") or 0),
                expected_sha256=str(
                    artifact.get("content_hash") or ""
                ).strip().lower().removeprefix("sha256:"),
            )
            projection = self.state.local_run_projection.mark_artifact_uploaded(
                str(session["username"]), job_id, name, transfer_id,
            )
        except KeyError as exc:
            json_response(self, {"success": False, "error": str(exc).strip("'")}, 404)
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return True
        json_response(self, {
            "success": True,
            "local_run": projection["job"],
            "task_detail": projection["task_detail"],
            "raw_artifacts_remote": True,
        })
        return True

    def _get_local_run_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/local-runs":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            query = parse_qs(parsed.query, keep_blank_values=True)
            try:
                page = max(1, int(query.get("page", ["1"])[0] or 1))
                limit = max(1, min(100, int(query.get("limit", ["20"])[0] or 20)))
            except (TypeError, ValueError):
                json_response(self, {"success": False, "error": "分页参数无效"}, 400)
                return True
            json_response(self, self.state.local_run_projection.page(
                str(session["username"]), page=page, limit=limit,
            ))
            return True
        match = re.fullmatch(
            r"/api/client/local-runs/([A-Za-z0-9._-]{1,128})", parsed.path,
        )
        if match is None:
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        value = self.state.local_run_projection.get(
            str(session["username"]), match.group(1),
        )
        if value is None:
            json_response(self, {"success": False, "error": "local run was not found"}, 404)
        else:
            json_response(self, {
                "success": True,
                "task_detail": value["task_detail"],
                "result_summary": value["result_summary"],
                "raw_artifacts_remote": value["raw_artifacts_remote"],
            })
        return True


def _artifact(projection: dict, name: str) -> dict:
    value = next(
        (item for item in projection["task_detail"].get("artifacts") or ()
         if str(item.get("name") or "") == name),
        None,
    )
    if value is None:
        raise KeyError("local artifact was not found")
    return value


__all__ = ["ClientLocalRunRoutesMixin"]
