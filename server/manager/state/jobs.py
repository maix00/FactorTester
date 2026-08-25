"""Local, federated, and cross-server job projections."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode, urlparse

from server.manager.config import MAIN_PORT
from server.manager.domain.federation import ServiceRoute, TargetUnavailable
from server.manager.http.gateway import GatewayResponse


def _object_job_query(
    object_kind: str, object_ref: str, owner_ref: str, alias: str,
) -> dict[str, str]:
    values = {
        "object_kind": str(object_kind or "").strip(),
        "object_ref": str(object_ref or "").strip(),
        "object_owner_ref": str(owner_ref or "").strip(),
        "object_alias": str(alias or "").strip(),
    }
    return {key: value for key, value in values.items() if value}


def _job_matches_object(
    job: dict[str, object], *, object_kind: str, object_ref: str,
    object_owner_ref: str, object_alias: str,
) -> bool:
    kind = str(object_kind or "").strip()
    if not kind:
        return True
    for item in job.get("object_subjects") or ():
        if not isinstance(item, dict) or item.get("object_kind") != kind:
            continue
        if kind == "family" and object_owner_ref and object_alias:
            if (str(item.get("owner_ref") or "") == object_owner_ref
                    and str(item.get("alias") or "") == object_alias):
                return True
        elif str(item.get("object_ref") or "") == object_ref:
            return True
    return False


def _filter_object_jobs(
    jobs: list[dict[str, object]], **query: str,
) -> list[dict[str, object]]:
    return [item for item in jobs if _job_matches_object(item, **query)]


class JobProjectionStateMixin:
    """Own job indexing and on-demand peer aggregation semantics."""

    _CROSS_SERVER_CACHE_SECONDS = 5.0

    def _cross_server_cache_get(
        self, key: tuple[object, ...],
    ) -> dict[str, object] | None:
        lock = getattr(self, "_cross_server_cache_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._cross_server_cache_lock = lock
        with lock:
            cache = getattr(self, "_cross_server_job_cache", None) or {}
            self._cross_server_job_cache = cache
            item = cache.get(key)
            if item is None:
                return None
            timestamp, value = item
            if time.monotonic() - float(timestamp) >= self._CROSS_SERVER_CACHE_SECONDS:
                cache.pop(key, None)
                return None
            return dict(value)

    def _cross_server_cache_put(
        self, key: tuple[object, ...], value: dict[str, object],
    ) -> dict[str, object]:
        lock = getattr(self, "_cross_server_cache_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._cross_server_cache_lock = lock
        with lock:
            cache = getattr(self, "_cross_server_job_cache", None) or {}
            cache[key] = (time.monotonic(), dict(value))
            self._cross_server_job_cache = cache
        return value
    def refresh_local_job_projection(self) -> None:
        """Refresh local summaries so control events are automatic.

        The server-wide endpoint is intentionally queried once.  Its summary
        includes the owner, so index both the public projection and each
        owner's private projection from the same response.  Without the
        private upsert a peer could receive the public event but still show an
        empty ``scope=mine`` list after the control sync caught up.
        """
        for port in self.service_ports():
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?scope=server&limit=100",
                    "__public_jobs__",
                )
            except (ConnectionError, OSError, TypeError, ValueError):
                continue
            jobs: list[dict[str, object]] = []
            for item in value.get("jobs") or []:
                if not isinstance(item, dict):
                    continue
                raw_port = item.get("port") or item.get("service_port") or port
                try:
                    job_port = int(raw_port)
                except (TypeError, ValueError):
                    job_port = port
                jobs.append(self._annotate_local_job(item, job_port))
            self.job_index.upsert("__public_jobs__", jobs)
            by_owner: dict[str, list[dict[str, object]]] = {}
            for job in jobs:
                owner = str(job.get("owner") or "").strip()
                if owner and owner != "__public_jobs__":
                    by_owner.setdefault(owner, []).append(job)
            for owner, owner_jobs in by_owner.items():
                self.job_index.upsert(owner, owner_jobs)

    def sync_local_maintenance(self) -> None:
        replication = getattr(self, "public_factor_replication", None)
        if replication is not None:
            replication.sync_pending()

    def aggregate_jobs(self, principal: str) -> list[dict[str, object]]:
        jobs: list[dict[str, object]] = []
        ports = self.service_ports()
        with ThreadPoolExecutor(max_workers=min(len(ports), 8) or 1) as pool:
            requests = {
                pool.submit(
                    self.service_json, port, "/api/jobs?limit=200", principal,
                ): port
                for port in ports
            }
            for future in as_completed(requests):
                port = requests[future]
                try:
                    values = future.result().get("jobs") or []
                except Exception:
                    continue
                for item in values:
                    if isinstance(item, dict):
                        jobs.append(self._annotate_local_job(item, port))
        self.job_index.upsert(principal, jobs)
        return self.job_index.list(principal)

    def has_federated_servers(self) -> bool:
        return bool(self.federation_registry.servers(include_offline=True))

    def federated_job_routes(
        self, *, allow_partial: bool = False,
    ) -> list[ServiceRoute]:
        """Return service targets for a bounded fan-out query.

        Direct execution and transfer routing still use the strict default:
        an explicitly registered offline target is an error.  Read-only list
        projections may opt into a partial result so one stopped worktree does
        not hold every online server's task list hostage.
        """
        routes = self.service_routes(include_offline=True)
        offline = [
            route for route in routes
            if (route.remote or route.port == self.fixed_port) and not route.online
        ]
        if offline and not allow_partial:
            names = ", ".join(
                f"{route.server_id}:{route.port}" for route in offline
            )
            raise TargetUnavailable(f"registered service target is offline: {names}")
        online = [route for route in routes if route.online]
        if not online:
            raise TargetUnavailable("no online service target")
        return online

    @staticmethod
    def _annotate_route_jobs(
        route: ServiceRoute,
        value: dict[str, object],
    ) -> list[dict[str, object]]:
        jobs: list[dict[str, object]] = []
        for item in value.get("jobs") or []:
            if not isinstance(item, dict):
                continue
            raw_port = item.get("port") or item.get("service_port") or route.port
            try:
                job_port = int(raw_port)
            except (TypeError, ValueError):
                job_port = route.port
            execution_server_id = str(
                item.get("execution_server_id") or route.server_id
            ).strip() or route.server_id
            try:
                execution_port = int(
                    item.get("execution_port") or job_port
                )
            except (TypeError, ValueError):
                execution_port = job_port
            endpoint = str(route.endpoint or "")
            host = urlparse(endpoint).hostname or ""
            jobs.append({
                **item,
                "port": job_port,
                "service_port": job_port,
                "server_id": route.server_id,
                "execution_server_id": execution_server_id,
                "execution_port": execution_port,
                "server_endpoint": endpoint,
                "server_host": host,
                "server_role": route.role,
                "server_branch": route.branch,
                "server_revision": route.revision,
            })
        return jobs

    def _annotate_local_job(
        self,
        value: dict[str, object],
        port: int,
    ) -> dict[str, object]:
        """Attach stable local execution identity before indexing a summary."""
        route = self._local_job_route_cache.get(int(port))
        if route is None:
            route = next(
                (
                    item for item in self.local_service_routes(include_offline=True)
                    if int(item.port) == int(port)
                ),
                None,
            )
        if route is None:
            route = self._local_route(port=int(port), online=True)
        self._local_job_route_cache[int(port)] = route
        annotated = self._annotate_route_jobs(route, {
            "jobs": [{**value, "port": int(port)}],
        })
        return annotated[0] if annotated else {**value, "port": int(port)}

    def record_run_submission(
        self,
        response: GatewayResponse,
        *,
        principal: str,
        route: ServiceRoute,
        origin_server_id: str = "",
    ) -> None:
        """Record a run placement after a successful submission response."""
        if not 200 <= int(response.status) < 300:
            return
        try:
            value = response.json_object()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return
        run = value.get("run")
        run_value = run if isinstance(run, dict) else value
        run_id = str(run_value.get("run_id") or "").strip()
        if not run_id:
            return
        self.job_index.record_run_routing(
            run_id=run_id,
            principal=principal,
            origin_server_id=str(origin_server_id or self.server_id),
            execution_server_id=route.server_id,
            execution_port=route.port,
            execution_branch=route.branch,
            execution_revision=route.revision,
        )

    def _federated_job_projection(
        self,
        *,
        principal: str,
        scope: str,
        limit: int,
        page: int = 1,
        username: str = "",
        allow_partial: bool = False,
    ) -> list[dict[str, object]]:
        query = {"scope": scope, "limit": str(max(1, min(100, int(limit))))}
        if scope == "subordinates" and username:
            query["username"] = username
        path = "/api/jobs?" + urlencode(query)
        combined: dict[str, dict[str, object]] = {}
        routes = self.federated_job_routes(allow_partial=allow_partial)

        def query_route(route: ServiceRoute) -> tuple[ServiceRoute, dict[str, object]]:
            return route, self.route_json(route, path=path, principal=principal)

        # A federated list is a read-only fan-out.  Serially waiting for every
        # local port and peer made the page latency equal to the sum of all
        # nodes' response times.  Keep the strict route-selection semantics,
        # but query the selected sources concurrently.
        with ThreadPoolExecutor(max_workers=min(len(routes), 8) or 1) as pool:
            futures = {
                pool.submit(query_route, route): route for route in routes
            }
            for future in as_completed(futures):
                route = futures[future]
                try:
                    _route, value = future.result()
                except (ConnectionError, OSError, TypeError, ValueError):
                    if not allow_partial:
                        raise
                    continue
                for item in self._annotate_route_jobs(route, value):
                    job_id = str(item.get("job_id") or "").strip()
                    if not job_id:
                        continue
                    # Jobs are normally unique per source, but retain the
                    # newest projection if an old index leaks a duplicate.
                    key = (
                        str(item.get("server_id") or route.server_id),
                        int(item.get("port") or route.port),
                        job_id,
                    )
                    current = combined.get(key)
                    if current is None or str(item.get("updated_at") or "") >= str(
                        current.get("updated_at") or ""
                    ):
                        combined[key] = item
        return sorted(
            combined.values(),
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("job_id") or ""),
            ),
            reverse=True,
        )

    def aggregate_federated_public_jobs(
        self, *, limit: int = 20,
    ) -> dict[str, object]:
        bounded = max(1, min(20, int(limit)))
        cached = self.job_index.list("__public_jobs__", limit=bounded)
        if cached or self._has_control_sync_snapshot():
            return {
                "public": True,
                "jobs": cached,
                "page_size": len(cached),
                "page": 1,
                "total": len(cached),
                "total_pages": 1,
                "has_more": False,
                "next_cursor": None,
                "sync_mode": "projection",
            }
        jobs = self._federated_job_projection(
            principal="__public_jobs__", scope="server", limit=limit,
        )[:20]
        self.job_index.upsert("__public_jobs__", jobs, emit_events=False)
        return {
            "public": True,
            "jobs": jobs,
            "page_size": len(jobs),
            "page": 1,
            "total": len(jobs),
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
            "sync_mode": "fanout_bootstrap",
        }
    def aggregate_federated_server_jobs(
        self, *, principal: str, limit: int = 20,
    ) -> dict[str, object]:
        bounded = max(1, min(100, int(limit)))
        cached = self.job_index.page(
            "__public_jobs__", page=1, limit=bounded,
        )
        if cached["jobs"] or self._has_control_sync_snapshot():
            return {
                "public": False,
                "jobs": cached["jobs"],
                "page_size": cached["page_size"],
                "page": cached["page"],
                "total": cached["total"],
                "total_pages": cached["total_pages"],
                "has_more": cached["has_more"],
                "next_cursor": None,
                "sync_mode": "projection",
            }
        jobs = self._federated_job_projection(
            principal=principal, scope="server", limit=limit,
        )
        self.job_index.upsert(principal, jobs, emit_events=False)
        self.job_index.upsert("__public_jobs__", jobs, emit_events=False)
        bounded = max(1, min(100, int(limit)))
        page_jobs = jobs[:bounded]
        return {
            "public": False,
            "jobs": page_jobs,
            "page_size": len(page_jobs),
            "page": 1,
            "total": len(jobs),
            "total_pages": max(1, (len(jobs) + bounded - 1) // bounded),
            "has_more": len(jobs) > len(page_jobs),
            "next_cursor": None,
            "sync_mode": "fanout_bootstrap",
        }

    def aggregate_federated_account_jobs(
        self,
        *,
        principal: str,
        scope: str,
        username: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, object]:
        cache_principal = str(username or principal).strip()
        bounded = max(1, min(100, int(limit)))
        requested_page = max(1, int(page))
        cache_key = (
            "federated-account", str(principal), str(scope), cache_principal,
            requested_page, bounded,
        )
        cached = self._cross_server_cache_get(cache_key)
        if cached is not None:
            cached["sync_mode"] = "cache"
            return cached
        # Fetch enough rows from every source to assemble a global page.  Each
        # source is queried from page one; slicing each source's page before
        # merging would make page two empty as soon as jobs are split across
        # Managers.
        source_limit = min(100, bounded * requested_page)
        jobs = self._federated_job_projection(
            principal=principal,
            scope=scope,
            username=username,
            limit=source_limit,
            page=1,
            allow_partial=True,
        )
        self.job_index.upsert(cache_principal, jobs, emit_events=False)
        start = (requested_page - 1) * bounded
        page_jobs = jobs[start:start + bounded]
        return self._cross_server_cache_put(cache_key, {
            "success": True,
            "scope": scope,
            "jobs": page_jobs,
            "page": requested_page,
            "page_size": len(page_jobs),
            "total": len(jobs),
            "total_pages": max(1, (len(jobs) + bounded - 1) // bounded),
            "has_more": start + len(page_jobs) < len(jobs),
            "next_cursor": None,
            "sync_mode": "on_demand",
        })

    def _has_control_sync_snapshot(self) -> bool:
        status = self.federation_sync.status()
        return any(
            str(item.get("status") or "") == "ok"
            for item in status.get("last_report") or []
            if isinstance(item, dict)
        )

    def aggregate_public_jobs(
        self, *, cursor: str = "", limit: int = 20,
        object_kind: str = "", object_ref: str = "",
        object_owner_ref: str = "", object_alias: str = "",
        _allow_federation: bool = True,
    ) -> dict[str, object]:
        """Read one public page from the service-wide job repository.

        Public jobs are already indexed in one service database.  Fan-out
        polling every running port made the anonymous page both slow and
        unable to paginate.  Try the preferred live service first and use
        another running service only when the first one is unavailable; the
        returned port is retained only for detail routing.
        """
        bounded_limit = min(20, max(1, int(limit)))
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query = {"scope": "server", "limit": str(bounded_limit)}
            query.update(_object_job_query(
                object_kind, object_ref, object_owner_ref, object_alias,
            ))
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    "__public_jobs__",
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append(self._annotate_local_job(item, job_port))
                # Anonymous and ordinary accounts receive a fixed public
                # snapshot, not a paginated view of the complete server
                # history.  A service may still return a cursor for its own
                # internal page, so discard it at the Manager boundary.
                jobs = jobs[:20]
                self.job_index.upsert("__public_jobs__", jobs)
                return {
                    "public": True,
                    "jobs": jobs,
                    "page_size": len(jobs),
                    "page": 1,
                    "total": len(jobs),
                    "total_pages": 1,
                    "has_more": False,
                    "next_cursor": None,
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached = [] if cursor else _filter_object_jobs(
            self.job_index.list_all(limit=2000),
            object_kind=object_kind, object_ref=object_ref,
            object_owner_ref=object_owner_ref, object_alias=object_alias,
        )[:bounded_limit]
        return {
            "public": True,
            "jobs": cached,
            "page_size": len(cached),
            "page": 1,
            "total": len(cached),
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
            "stale": bool(cached),
        }

    def aggregate_server_jobs(
        self, *, principal: str, cursor: str = "", limit: int = 20,
        object_kind: str = "", object_ref: str = "",
        object_owner_ref: str = "", object_alias: str = "",
        _allow_federation: bool = True,
    ) -> dict[str, object]:
        """Read the permissioned server projection for a Manager user.

        Super-admins receive the complete server projection.  If the selected
        service is an old process and cannot accept Manager authentication,
        the cross-principal index remains a bounded, read-only fallback.
        """
        bounded_limit = min(100, max(1, int(limit)))
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query = {"scope": "server", "limit": str(bounded_limit)}
            query.update(_object_job_query(
                object_kind, object_ref, object_owner_ref, object_alias,
            ))
            if cursor:
                query["cursor"] = cursor
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    principal,
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append(self._annotate_local_job(item, job_port))
                self.job_index.upsert(principal, jobs)
                self.job_index.upsert("__public_jobs__", jobs, emit_events=False)
                return {
                    "public": False,
                    "jobs": jobs,
                    "page_size": len(jobs),
                    "page": value.get("page", 1),
                    "total": value.get("total", len(jobs)),
                    "total_pages": value.get("total_pages", 1),
                    "has_more": bool(value.get("has_more")),
                    "next_cursor": value.get("next_cursor"),
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached = [] if cursor else _filter_object_jobs(
            self.job_index.list_all(limit=2000),
            object_kind=object_kind, object_ref=object_ref,
            object_owner_ref=object_owner_ref, object_alias=object_alias,
        )[:bounded_limit]
        return {
            "public": False,
            "jobs": cached,
            "page_size": len(cached),
            "page": 1,
            "total": len(cached),
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
            "stale": bool(cached),
        }

    def aggregate_account_jobs(
        self,
        *,
        principal: str,
        scope: str,
        username: str = "",
        page: int = 1,
        limit: int = 20,
        object_kind: str = "", object_ref: str = "",
        object_owner_ref: str = "", object_alias: str = "",
        _allow_federation: bool = True,
    ) -> dict[str, object]:
        """Read one account projection from the shared job repository.

        Every FactorTester service points at the same durable job index.  The
        Manager therefore asks one live service for the requested projection,
        rather than polling each port.  Its local index remains a bounded
        fallback for a temporary service restart and for detail routing.
        """
        bounded_limit = min(100, max(1, int(limit)))
        requested_page = max(1, int(page))
        cache_principal = str(username or principal).strip()
        ordered_ports = self.ordered_job_service_ports()
        for port in ordered_ports:
            query: dict[str, str] = {
                "scope": scope,
                "limit": str(bounded_limit),
                "page": str(requested_page),
            }
            query.update(_object_job_query(
                object_kind, object_ref, object_owner_ref, object_alias,
            ))
            if scope == "subordinates" and username:
                query["username"] = username
            try:
                value = self.service_json(
                    port,
                    "/api/jobs?" + urlencode(query),
                    principal,
                )
                jobs: list[dict[str, object]] = []
                for item in value.get("jobs") or []:
                    if not isinstance(item, dict):
                        continue
                    raw_port = item.get("port") or item.get("service_port") or port
                    try:
                        job_port = int(raw_port)
                    except (TypeError, ValueError):
                        job_port = port
                    jobs.append(self._annotate_local_job(item, job_port))
                self.job_index.upsert(cache_principal, jobs)
                return {
                    **value,
                    "success": True,
                    "scope": scope,
                    "jobs": jobs,
                    "page": value.get("page", requested_page),
                }
            except (ConnectionError, OSError, TypeError, ValueError):
                continue

        cached_rows = _filter_object_jobs(
            self.job_index.list(cache_principal, limit=2000),
            object_kind=object_kind, object_ref=object_ref,
            object_owner_ref=object_owner_ref, object_alias=object_alias,
        )
        start = (requested_page - 1) * bounded_limit
        cached = {
            "jobs": cached_rows[start:start + bounded_limit],
            "page": requested_page,
            "page_size": min(bounded_limit, max(0, len(cached_rows) - start)),
            "total": len(cached_rows),
            "total_pages": max(1, (len(cached_rows) + bounded_limit - 1) // bounded_limit),
            "has_more": start + bounded_limit < len(cached_rows),
            "next_cursor": None,
        }
        return {
            **cached,
            "success": True,
            "scope": scope,
            "stale": bool(cached["jobs"]),
        }

    def _federation_manager_routes(self) -> list[ServiceRoute]:
        """Choose one 7998 route per registered peer Manager."""
        result: list[ServiceRoute] = []
        for server in self.federation_registry.servers(include_offline=True):
            server_id = str(server.get("server_id") or "").strip()
            candidates = [
                route for route in self.federation_registry.routes(
                    include_offline=True,
                ) if route.server_id == server_id
            ]
            if not candidates:
                continue
            result.append(sorted(
                candidates,
                key=lambda route: (
                    0 if int(route.port) == MAIN_PORT else 1,
                    int(route.port),
                ),
            )[0])
        return result

    def aggregate_cross_server_jobs(
        self,
        *,
        principal: str,
        page: int = 1,
        limit: int = 20,
        source_scope: str = "mine",
        username: str = "",
        object_kind: str = "", object_ref: str = "",
        object_owner_ref: str = "", object_alias: str = "",
    ) -> dict[str, object]:
        """Fan out a bounded read when the cross-server tab is opened.

        This intentionally does not write ``job-index.sqlite`` or advance a
        control-event cursor.  Every source remains authoritative for its
        local SQLite queue; the Manager merges short-lived summaries and
        retains the source identity needed for a later detail/artifact route.
        """
        bounded = min(100, max(1, int(limit)))
        requested_page = max(1, int(page))
        # Every source contributes to one globally ordered list.  Fetch from
        # page one with enough rows to assemble the requested global page;
        # asking each source for page N and then slicing the merged result
        # would skip rows whenever the sources have different lengths.
        source_limit = min(100, bounded * requested_page)
        source_scope = str(source_scope or "mine").strip().lower()
        username = str(username or "").strip()
        if source_scope not in {"mine", "subordinates", "visible", "server"}:
            raise ValueError(
                "cross-server source scope must be mine, subordinates, visible, or server"
            )
        if source_scope == "subordinates" and not username:
            raise ValueError("username is required for subordinate jobs")
        cache_key = (
            str(principal), source_scope, username, requested_page, bounded,
            object_kind, object_ref, object_owner_ref, object_alias,
        )
        cached = self._cross_server_cache_get(cache_key)
        if cached is not None:
            cached["sync_mode"] = "cache"
            return cached

        combined: list[dict[str, object]] = []
        source_status: list[dict[str, object]] = []
        object_query = _object_job_query(
            object_kind, object_ref, object_owner_ref, object_alias,
        )

        def query_local() -> tuple[dict[str, object], list[dict[str, object]]]:
            if source_scope == "server":
                local_payload = self.aggregate_server_jobs(
                    principal=principal,
                    limit=source_limit,
                    **object_query,
                    _allow_federation=False,
                )
            else:
                account_query = {
                    "principal": principal,
                    "scope": source_scope,
                    "page": 1,
                    "limit": source_limit,
                    "_allow_federation": False,
                    **object_query,
                }
                if username:
                    account_query["username"] = username
                local_payload = self.aggregate_account_jobs(**account_query)
            local_jobs: list[dict[str, object]] = []
            for item in local_payload.get("jobs") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("server_id") or "").strip():
                    local_jobs.append(item)
                    continue
                try:
                    local_port = int(
                        item.get("port") or item.get("service_port") or 0,
                    )
                except (TypeError, ValueError):
                    local_port = 0
                local_jobs.append(self._annotate_local_job(item, local_port))
            return local_payload, local_jobs

        def query_peer(route: ServiceRoute) -> tuple[ServiceRoute, dict[str, object]]:
            return route, self.federation_gateway.query_jobs(
                route,
                requester_server_id=self.server_id,
                principal=principal,
                scope=source_scope,
                page=1,
                limit=source_limit,
                username=username,
                **object_query,
            )

        peer_routes = self._federation_manager_routes()
        for route in peer_routes:
            if not route.online:
                source_status.append({
                    "server_id": route.server_id,
                    "endpoint": route.endpoint,
                    "status": "offline",
                    "job_count": 0,
                    "total": 0,
                    "error": "registered server is offline",
                })
        online_peer_routes = [route for route in peer_routes if route.online]
        # The local service request used to finish before any peer request was
        # submitted.  A slow worktree therefore blocked every remote source
        # even though the federation gateway could already be serving them.
        # Submit the local and peer reads together; the persistent source
        # status still records each result independently.
        with ThreadPoolExecutor(
            max_workers=min(1 + len(online_peer_routes), 8),
        ) as pool:
            futures = {
                pool.submit(query_local): None,
                **{
                    pool.submit(query_peer, route): route
                    for route in online_peer_routes
                },
            }
            for future in as_completed(futures):
                route = futures[future]
                if route is None:
                    try:
                        local_payload, local_jobs = future.result()
                    except (ConnectionError, OSError, TypeError, ValueError) as exc:
                        source_status.append({
                            "server_id": self.server_id,
                            "status": "error",
                            "job_count": 0,
                            "total": 0,
                            "error": str(exc),
                        })
                        continue
                    combined.extend(local_jobs)
                    source_status.append({
                        "server_id": self.server_id,
                        "endpoint": os.environ.get(
                            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
                            "http://127.0.0.1:7998",
                        ),
                        "status": "ok" if not local_payload.get("stale") else "stale",
                        "job_count": len(local_jobs),
                        "total": int(local_payload.get("total") or len(local_jobs)),
                        "has_more": bool(local_payload.get("has_more")),
                    })
                    continue
                base_status = {
                    "server_id": route.server_id,
                    "endpoint": route.endpoint,
                    "status": "ok",
                }
                try:
                    _route, payload = future.result()
                except (ConnectionError, OSError, TypeError, ValueError) as exc:
                    source_status.append({
                        **base_status,
                        "status": "error",
                        "job_count": 0,
                        "total": 0,
                        "error": str(exc),
                    })
                    continue
                jobs = self._annotate_route_jobs(route, payload)
                combined.extend(jobs)
                source_status.append({
                    **base_status,
                    "job_count": len(jobs),
                    "total": int(payload.get("total") or len(jobs)),
                    "has_more": bool(payload.get("has_more")),
                })

        def sort_key(item: dict[str, object]) -> tuple[object, str, str, int]:
            try:
                port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            return (
                self.job_index._updated_order(item.get("updated_at")),
                str(item.get("server_id") or ""),
                str(item.get("job_id") or ""),
                port,
            )

        unique: dict[tuple[str, int, str], dict[str, object]] = {}
        for item in combined:
            job_id = str(item.get("job_id") or "").strip()
            if not job_id:
                continue
            try:
                port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            key = (str(item.get("server_id") or self.server_id), port, job_id)
            current = unique.get(key)
            if current is None or sort_key(item) > sort_key(current):
                unique[key] = item
        ordered = sorted(unique.values(), key=sort_key, reverse=True)
        total = sum(
            int(item.get("total") or 0)
            for item in source_status
            if str(item.get("status") or "") in {"ok", "stale"}
        )
        total = max(total, len(ordered))
        start = (requested_page - 1) * bounded
        page_jobs = ordered[start:start + bounded]
        has_more = start + bounded < total or any(
            bool(item.get("has_more"))
            for item in source_status
            if str(item.get("status") or "") in {"ok", "stale"}
        )
        return self._cross_server_cache_put(cache_key, {
            "success": True,
            "scope": "cross-server",
            "source_scope": source_scope,
            "sync_mode": "on_demand",
            "jobs": page_jobs,
            "page": requested_page,
            "page_size": len(page_jobs),
            "total": total,
            "total_pages": max(1, (total + bounded - 1) // bounded),
            "has_more": has_more,
            "next_cursor": None,
            "partial": any(
                str(item.get("status") or "") not in {"ok", "stale"}
                for item in source_status
            ),
            "sources": sorted(
                source_status,
                key=lambda item: str(item.get("server_id") or ""),
            ),
        })
