"""Product, factor, and test-authoring HTTP projections."""

from __future__ import annotations

import re
import sys
from urllib.parse import parse_qs, unquote

from server.manager.http.product_library_routes import (
    PRODUCT_LIBRARY_PREFIX,
    product_library_page,
    product_library_source_ids,
)
from server.manager.http.responses import json_response
from server.manager.services.public_catalog import (
    VisitorCatalogAccessError,
    ensure_visitor_product_access,
    filter_product_rows,
    select_visitor_source_ids,
    visitor_local_source_ids,
    visitor_source_descriptors,
)
from server.manager.services.test_authoring import TestAuthoringError
from server.modules.products.product_category_views import normalize_category_selection


def _factor_resource_projection(
    payload: dict[str, object], resource: str,
) -> dict[str, object]:
    """Expose one canonical factor-library resource without a mixed catalog."""
    keep = "families" if resource == "families" else "factors"
    drop = "factors" if keep == "families" else "families"
    result = dict(payload)
    result.pop(drop, None)
    scopes = result.get("family_scopes")
    if isinstance(scopes, dict):
        result["family_scopes"] = {
            key: {
                **value,
                keep: list(value.get(keep) or []),
                **({drop: []} if drop in value else {}),
            }
            for key, value in scopes.items()
            if isinstance(value, dict)
        }
    return result


class CatalogRoutesMixin:
    """Serve Manager-owned catalogs without consulting execution ports."""

    def _serve_report_reference(self, parsed) -> bool:
        if parsed.path != "/api/report-references/validate":
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        from server.modules.shared.price_services import (
            cached_contracts,
            cached_products,
        )
        from server.services.report_reference_resolution import (
            validate_report_reference,
        )

        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            reference = validate_report_reference(
                kind=str(query.get("kind", [""])[0] or ""),
                target_ref=str(query.get("target_ref", [""])[0] or ""),
                products=cached_products(),
                contracts=cached_contracts(),
            )
        except (LookupError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        json_response(self, {"success": True, "reference": reference})
        return True

    def _visible_factor_set_owner(
        self, principal: str, target_ref: str, requested_owner: str,
    ) -> str:
        """Resolve own/direct-child Factor Set ownership once for all reads."""
        owner = str(requested_owner or "").strip()
        if owner == principal:
            return principal
        reader = getattr(self.state.client_state, "factor_set_scopes", None)
        scopes = reader(principal) if callable(reader) else {}
        if not owner and any(str(item.get("target_ref") or "") == target_ref
                             for item in scopes.get("mine") or []):
            return principal
        matches = {
            str(item.get("owner_username") or "")
            for item in scopes.get("subordinates") or []
            if str(item.get("target_ref") or "") == target_ref
            and (not owner or str(item.get("owner_username") or "") == owner)
        } - {""}
        if len(matches) == 1:
            return matches.pop()
        if not owner and not matches:
            # Preserve the own-set 404 response without searching other users.
            return principal
        raise PermissionError("无权查看该用户因子集合")

    def _ensure_visitor_price_access(self, payload: dict) -> None:
        """Reject price requests whose product is internal-only.

        Visitor mode may read a curve only when the current public Manager
        owns a public provider for the product.  The catalog endpoint keeps
        source metadata visible, so this check must happen again at the byte
        serving boundary.
        """
        from server.modules.shared.price_services import find_contract_product

        product_name = str(payload.get("product_name") or "").strip()
        if not product_name and payload.get("contract_uid"):
            contract = find_contract_product(str(payload["contract_uid"]))
            parent = getattr(contract, "parent_product", None)
            if callable(parent):
                parent = parent()
            if parent is None and contract is not None:
                parent = getattr(contract, "get_parent_product", lambda: None)()
            product_name = str(
                getattr(parent, "name", "")
                or getattr(contract, "name", "")
                or "",
            ).strip()
        product = (
            self.state.client_state.product_fields(product_name)
            if product_name else None
        )
        descriptors = visitor_source_descriptors(
            self.state.federated_source_descriptors(),
            local_server_id=self.state.server_id,
        )
        ensure_visitor_product_access(
            product, visitor_local_source_ids(descriptors),
        )

    def _serve_product_catalog(self, parsed) -> bool:
        """Serve the Manager-owned catalog without selecting a service port."""
        if not parsed.path.startswith(PRODUCT_LIBRARY_PREFIX):
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and visitor is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        principal = str(
            session["username"] if session is not None else visitor.principal
        )
        query = parse_qs(parsed.query, keep_blank_values=True)
        category_ids = normalize_category_selection(query.get("category", []))
        checkbox = str(query.get("checkbox", [""])[0] or "").lower() in {
            "1", "true",
        }
        category_arg = (
            category_ids[0] if len(category_ids) == 1
            else category_ids if category_ids else ""
        )
        category_id = category_ids[0] if len(category_ids) == 1 else ",".join(category_ids)
        try:
            if parsed.path == "/api/product-library/data-sources":
                sources = self.state.federated_source_descriptors(
                    refresh=str(query.get("refresh", [""])[0]).lower()
                    in {"1", "true", "yes"},
                )
                if visitor is not None:
                    sources = visitor_source_descriptors(
                        sources, local_server_id=self.state.server_id,
                    )
                value = {
                    "success": True,
                    "origin": "server",
                    "visitor": visitor is not None,
                    "sources": sources,
                }
            elif parsed.path == "/api/product-library/categories":
                value = {
                    "success": True,
                    "origin": "server",
                    "default_category_id": None,
                    "categories": self.state.client_state.product_categories(principal),
                }
            elif parsed.path == "/api/product-library/products":
                if visitor is not None:
                    descriptors = visitor_source_descriptors(
                        self.state.federated_source_descriptors(),
                        local_server_id=self.state.server_id,
                    )
                    source_ids = select_visitor_source_ids(query, descriptors)
                    products = filter_product_rows(
                        self.state.client_state.product_names(), source_ids,
                    )
                else:
                    source_ids = product_library_source_ids(query)
                    products = self.state.client_state.product_names(source_ids)
                value = {
                    "success": True,
                    "origin": "server",
                    "visitor": visitor is not None,
                    "source_ids": list(source_ids),
                    "products": products,
                }
                if any(key in query for key in ("query", "page", "limit")):
                    value.update(product_library_page(products, query))
            elif parsed.path == "/api/product-library/product-fields":
                product = self.state.client_state.product_fields(
                    query.get("name", [""])[0]
                )
                if visitor is not None:
                    descriptors = visitor_source_descriptors(
                        self.state.federated_source_descriptors(),
                        local_server_id=self.state.server_id,
                    )
                    ensure_visitor_product_access(
                        product, visitor_local_source_ids(descriptors),
                    )
                if product is None:
                    json_response(self, {
                        "success": False, "error": "产品不存在",
                    }, 404)
                    return True
                value = {
                    "success": True,
                    "origin": "server",
                    "name": product.get("name"),
                    "fields": product.get("fields", {}),
                }
            elif parsed.path == "/api/product-library/tree":
                if visitor is not None:
                    descriptors = visitor_source_descriptors(
                        self.state.federated_source_descriptors(),
                        local_server_id=self.state.server_id,
                    )
                    source_ids = select_visitor_source_ids(query, descriptors)
                else:
                    source_ids = product_library_source_ids(query)
                value = {
                    "success": True,
                    "origin": "server",
                    "visitor": visitor is not None,
                    "category_id": category_id,
                    "category_ids": category_ids,
                    "source_ids": list(source_ids),
                    "tree": (
                        self.state.client_state.product_tree(
                            category_arg, source_ids, principal,
                            checkbox_default=True,
                        )
                        if checkbox else self.state.client_state.product_tree(
                            category_arg, source_ids, principal,
                        )
                    ),
                }
            elif parsed.path == "/api/product-library/contract-tree":
                if visitor is not None:
                    descriptors = visitor_source_descriptors(
                        self.state.federated_source_descriptors(),
                        local_server_id=self.state.server_id,
                    )
                    source_ids = select_visitor_source_ids(query, descriptors)
                else:
                    source_ids = product_library_source_ids(query)
                paged = any(
                    key in query for key in ("query", "page", "limit")
                )
                if paged:
                    try:
                        page = max(1, int(query.get("page", ["1"])[0] or 1))
                        limit = min(100, max(
                            1, int(query.get("limit", ["25"])[0] or 25),
                        ))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("产品列表分页参数无效") from exc
                    nodes = self.state.client_state.contract_tree_page(
                        query.get("path", [""])[0], category_arg, source_ids,
                        principal,
                        query=str(query.get("query", [""])[0] or ""),
                        page=page,
                        limit=limit,
                    )
                else:
                    nodes = {
                        "nodes": self.state.client_state.contract_tree(
                            query.get("path", [""])[0], category_arg, source_ids,
                            principal,
                        ),
                    }
                value = {
                    "success": True,
                    "origin": "server",
                    "category_id": category_id,
                    "category_ids": category_ids,
                    "source_ids": list(source_ids),
                    **nodes,
                }
            elif parsed.path == "/api/product-library/contracts":
                if visitor is not None:
                    descriptors = visitor_source_descriptors(
                        self.state.federated_source_descriptors(),
                        local_server_id=self.state.server_id,
                    )
                    ensure_visitor_product_access(
                        self.state.client_state.product_fields(
                            str(query.get("product", [""])[0] or "")
                        ),
                        visitor_local_source_ids(descriptors),
                    )
                value = self.state.client_state.product_contracts(
                    str(query.get("product", [""])[0] or ""),
                    start_date=query.get("start_date", [None])[0],
                    end_date=query.get("end_date", [None])[0],
                )
            elif parsed.path == "/api/product-library/product-groups":
                summary = str(query.get("view", [""])[0] or "") == "summary"
                value = {
                    "success": True,
                    "origin": "server",
                    # Product groups created in visitor mode are stored under
                    # that visitor's UUID namespace.  They are temporary
                    # authoring objects, not another user's private groups.
                    "visitor": visitor is not None,
                    "groups": (
                        self.state.client_state.product_group_summaries(principal)
                        if summary
                        else self.state.client_state.product_groups(principal)
                    ),
                }
            else:
                subjects = re.fullmatch(
                    r"/api/product-library/product-groups/([^/]+)/subjects", parsed.path,
                )
                if subjects is not None:
                    bindings = self.state.client_state.product_group_subjects(
                        principal, unquote(subjects.group(1)),
                    )
                    if bindings is None:
                        json_response(self, {
                            "success": False, "error": "产品组不存在",
                        }, 404)
                        return True
                    value = {
                        "success": True,
                        "origin": "server",
                        "subjects": bindings,
                    }
                    json_response(self, value)
                    return True
                match = re.fullmatch(
                    r"/api/product-library/product-groups/([^/]+)", parsed.path,
                )
                if match is None:
                    return False
                group = self.state.client_state.product_group(
                    principal, unquote(match.group(1)),
                )
                if group is None:
                    json_response(self, {
                        "success": False, "error": "产品组不存在",
                    }, 404)
                    return True
                value = {"success": True, "origin": "server", "group": group}
        except ValueError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc)},
                int(getattr(exc, "status", 400)),
            )
            return True
        except (OSError, RuntimeError, ImportError, TypeError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, value)
        return True

    def _serve_factor_catalog(self, parsed) -> bool:
        """Serve read-only factor metadata without selecting a service port."""
        if not parsed.path.startswith("/api/factor-library/"):
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and visitor is None:
            json_response(self, {
                "success": False, "error": "login required",
            }, 401)
            return True
        principal = str(
            session["username"] if session is not None else visitor.principal
        )
        factor_service = getattr(self.state, "federated_public_data", None)
        if factor_service is None:
            factor_service = self.state.client_state
        query = parse_qs(parsed.query, keep_blank_values=True)
        refresh = str(query.get("refresh", [""])[0] or "") == "1"
        try:
            source_match = re.fullmatch(
                r"/api/factor-library/family-sources/(custom|public)/([^/]+)"
                r"/versions(?:/([^/]+))?",
                parsed.path,
            )
            if source_match is not None:
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能读取因子家族源码"
                    )
                from server.services.factor_source_catalog import (
                    FactorSourceCatalog,
                )

                catalog = FactorSourceCatalog()
                kind = source_match.group(1)
                factor_id = unquote(source_match.group(2))
                fingerprint = source_match.group(3)
                owner = str(
                    query.get("owner_username", [""])[0] or ""
                )
                selected_version = (
                    unquote(fingerprint)
                    if fingerprint is not None else None
                )
                if selected_version in (None, 'current'):
                    from server.manager.services.factor_family_current import ensure_current_family
                    if not ensure_current_family(self.state, kind, factor_id,
                                                 principal=principal, owner=owner):
                        raise FileNotFoundError('因子家族已删除或源码尚不可用')

                def read_source_catalog():
                    if selected_version is not None:
                        return catalog.version(
                            principal,
                            kind,
                            factor_id,
                            selected_version,
                            owner_username=owner,
                        )
                    return catalog.versions(
                        principal,
                        kind,
                        factor_id,
                        owner_username=owner,
                        limit=query.get("limit", ["100"])[0] or 100,
                    )

                try:
                    value = read_source_catalog()
                except FileNotFoundError:
                    from server.manager.services.factor_source_hydration import (
                        FactorSourceHydrator,
                    )

                    source_owner = (
                        "public" if kind == "public" else owner or principal
                    )
                    if not FactorSourceHydrator(self.state).hydrate(
                        f"{source_owner}:{factor_id}", principal=principal,
                        fingerprint=selected_version if selected_version not in (None, "current") else "",
                    ):
                        raise
                    value = read_source_catalog()
                json_response(self, value)
                return True
            if parsed.path == "/api/factor-library/family-sources/manifest":
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能同步因子家族源码"
                    )
                from server.services.factor_source_manifest import (
                    FactorSourceManifest,
                )

                json_response(self, FactorSourceManifest().build(
                    principal,
                    server_id=self.state.server_id,
                    include_subordinates=str(
                        query.get("include_subordinates", ["1"])[0] or "1"
                    ) == "1",
                ))
                return True
            provenance_match = re.fullmatch(
                r"/api/factor-library/owners"
                r"(?:/([^/]+)/projection)?",
                parsed.path,
            )
            if provenance_match is not None:
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能读取用户因子库来源"
                    )
                from server.services.factor_library_provenance import (
                    FactorLibraryProvenance,
                )

                catalog = factor_service.factor_library(principal)
                owner_ref = provenance_match.group(1)
                provenance = FactorLibraryProvenance()
                value = (
                    provenance.projection(
                        catalog,
                        principal=principal,
                        owner_ref=unquote(owner_ref),
                        product_group=str(
                            query.get("product_group", [""])[0] or ""
                        ),
                    )
                    if owner_ref is not None
                    else provenance.owners(catalog, principal=principal)
                )
                json_response(self, value)
                return True
            if parsed.path in {
                "/api/factor-library/families",
                "/api/factor-library/factors",
            }:
                if visitor is not None:
                    from server.manager.services.factor_library_scopes import (
                        compose_factor_library_scopes,
                    )
                    from server.manager.services.public_catalog import (
                        public_factor_library,
                    )
                    payload = {
                        "success": True,
                        "visitor": True,
                        **compose_factor_library_scopes(
                            {"public": public_factor_library()},
                            principal=principal,
                        ),
                    }
                    json_response(
                        self, _factor_resource_projection(
                            payload, parsed.path.rsplit("/", 1)[-1],
                        ),
                    )
                    return True
                if factor_service is self.state.client_state:
                    from server.manager.services.factor_library_scopes import (
                        compose_factor_library_scopes,
                    )
                    from server.manager.services.public_catalog import (
                        public_factor_library,
                    )
                    scope_reader = getattr(
                        factor_service, "factor_library_scopes", None,
                    )
                    scopes = {"public": public_factor_library()}
                    if callable(scope_reader):
                        scopes.update(
                            scope_reader(principal, refresh=refresh)
                            if refresh else scope_reader(principal)
                        )
                    else:
                        scopes["mine"] = (
                            factor_service.factor_library(
                                principal, refresh=True,
                            ) if refresh else factor_service.factor_library(principal)
                        )
                    value = compose_factor_library_scopes(
                        scopes, principal=principal,
                    )
                    json_response(
                        self, _factor_resource_projection(
                            {"success": True, **value},
                            parsed.path.rsplit("/", 1)[-1],
                        ),
                    )
                    return True
                payload = {
                    "success": True,
                    **(
                        factor_service.factor_library(
                            principal, refresh=True,
                        ) if refresh else factor_service.factor_library(principal)
                    ),
                }
                json_response(
                    self, _factor_resource_projection(
                        payload, parsed.path.rsplit("/", 1)[-1],
                    ),
                )
                return True
            if parsed.path == "/api/factor-library/factor-sets":
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能读取用户因子集合"
                    )
                needle = str(query.get("query", [""])[0] or "")
                scope_reader = getattr(factor_service, "factor_set_scopes", None)
                if callable(scope_reader):
                    scopes = scope_reader(principal, needle)
                    items = [
                        *list(scopes.get("mine") or []),
                        *list(scopes.get("subordinates") or []),
                    ]
                else:
                    items = factor_service.factor_sets(principal, needle)
                    scopes = {"mine": items, "subordinates": []}
                json_response(self, {
                    "success": True, "count": len(items), "items": items,
                    "item_scopes": scopes,
                })
                return True
            if parsed.path == "/api/factor-library/factor-sets/detail":
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能读取用户因子集合"
                    )
                offset = max(0, int(query.get("offset", ["0"])[0] or 0))
                limit = min(100, max(
                    1, int(query.get("limit", ["100"])[0] or 100),
                ))
                target_ref = str(
                    query.get("target_ref", [""])[0] or ""
                )
                owner = self._visible_factor_set_owner(
                    principal,
                    target_ref,
                    str(query.get("owner_username", [""])[0] or ""),
                )
                value = self.state.client_state.factor_set_detail(
                    owner,
                    target_ref,
                    offset=offset,
                    limit=limit,
                )
                if value is None:
                    json_response(self, {
                        "success": False, "error": "Factor Set 不存在",
                    }, 404)
                else:
                    json_response(self, {
                        "success": True, "factor_set": value,
                    })
                return True
            if parsed.path == "/api/factor-library/factor-sets/descriptor":
                if visitor is not None:
                    raise VisitorCatalogAccessError(
                        "访客模式不能读取用户因子集合"
                    )
                target_ref = str(
                    query.get("target_ref", [""])[0] or ""
                )
                owner = self._visible_factor_set_owner(
                    principal,
                    target_ref,
                    str(query.get("owner_username", [""])[0] or ""),
                )
                value = self.state.client_state.factor_set_descriptor(
                    owner, target_ref,
                )
                if value is None:
                    json_response(self, {
                        "success": False, "error": "Factor Set 不存在",
                    }, 404)
                else:
                    json_response(self, {
                        "success": True, "descriptor": value,
                    })
                return True
        except VisitorCatalogAccessError as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, int(getattr(exc, "status", 403)))
            return True
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return True
        except FileNotFoundError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return True
        except ValueError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (
            OSError, RuntimeError, ImportError, TypeError, KeyError,
        ) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 503)
            return True
        return False

    def _serve_factor_catalog_write(self, parsed, *, method: str) -> bool:
        """Write principal-owned Factor Sets without selecting a service port."""
        if parsed.path != "/api/factor-library/factor-sets":
            return False
        session = self._session()
        if session is None or self._visitor_mode() is not None:
            json_response(self, {
                "success": False, "error": "login required",
            }, 401)
            return True
        principal = str(session["username"])
        from server.modules.custom_factors.factor_set_registry import (
            author_factor_set,
            register_factor_set,
            unregister_factor_set,
        )

        try:
            if method == "DELETE":
                query = parse_qs(parsed.query, keep_blank_values=True)
                target_ref = str(
                    query.get("target_ref", [""])[0] or ""
                ).strip()
                if not target_ref:
                    raise ValueError("target_ref 不能为空")
                removed = unregister_factor_set(principal, target_ref)
                if removed:
                    self.state.client_state._refresh_account_domain_async(principal, force=True)
                json_response(self, {"success": removed})
                return True
            if method != "POST":
                return False
            payload = self._json_body(2 * 1024 * 1024)
            definition = payload.get("definition")
            if isinstance(definition, dict):
                value = author_factor_set(
                    principal,
                    definition,
                    persist=payload.get("persist") is not False,
                    replace_target_ref=str(
                        payload.get("replace_target_ref") or ""
                    ),
                )
            else:
                descriptor = payload.get("descriptor")
                if not isinstance(descriptor, dict):
                    raise ValueError("descriptor 必须是对象")
                value = register_factor_set(principal, descriptor)
        except (KeyError, TypeError, ValueError) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 400)
            return True
        except (OSError, RuntimeError, ImportError) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 503)
            return True
        if payload.get("persist") is not False:
            self.state.client_state._refresh_account_domain_async(principal, force=True)
        json_response(self, {"success": True, "factor_set": value})
        return True

    def _serve_product_catalog_write(self, parsed) -> bool:
        """Serve Manager-owned catalog writes without a service port."""
        category_delete = re.fullmatch(
            r"/api/product-library/categories/([^/]+)", parsed.path,
        )
        category_refresh = re.fullmatch(
            r"/api/product-library/categories/([^/]+)/refresh", parsed.path,
        )
        group_mutation = re.fullmatch(
            r"/api/product-library/product-groups/([^/]+)", parsed.path,
        )
        group_subjects = re.fullmatch(
            r"/api/product-library/product-groups/([^/]+)/subjects", parsed.path,
        )
        if parsed.path not in {
            "/api/market-data/prices",
            "/api/product-library/product-groups",
            "/api/product-library/categories",
            "/api/product-library/categories/composite",
        } and category_delete is None and category_refresh is None \
                and group_mutation is None and group_subjects is None:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and visitor is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        price_request = parsed.path == "/api/market-data/prices"
        if visitor is not None and not price_request:
            json_response(self, {
                "success": False,
                "error": "访客模式只能查看产品组，不能修改产品目录",
                "code": "visitor_catalog_write_forbidden",
            }, 403)
            return True
        principal = (
            visitor.principal
            if session is None and visitor is not None
            else str(session["username"])
        )
        try:
            method = str(getattr(self, "command", "POST") or "POST").upper()
            payload = {} if (
                (category_delete is not None and method == "DELETE")
                or (group_mutation is not None and method == "DELETE")
                or category_refresh is not None
            ) else self._json_body(256 * 1024)
            if price_request and visitor is not None:
                self._ensure_visitor_price_access(payload)
            if parsed.path == "/api/product-library/categories":
                from server.modules.products.product_category_store import (
                    create_product_category,
                )

                category = create_product_category(
                    principal,
                    payload.get("name"),
                    payload.get("items"),
                    category_id=payload.get("id"),
                )
                value = {"success": True, "origin": "server", "category": category}
            elif parsed.path == "/api/product-library/categories/composite":
                from server.modules.products.product_category_store import (
                    create_product_category_composition,
                )

                category = create_product_category_composition(
                    principal, payload.get("category_ids"),
                )
                value = {"success": True, "origin": "server", "category": category}
            elif category_refresh is not None and method == "POST":
                from server.modules.products.product_category_store import (
                    refresh_product_category_composition,
                )

                category = refresh_product_category_composition(
                    principal, unquote(category_refresh.group(1)),
                )
                if category is None:
                    json_response(self, {
                        "success": False, "error": "产品分类不存在",
                    }, 404)
                    return True
                value = {
                    "success": True, "origin": "server", "category": category,
                }
            elif category_delete is not None and method in {"PUT", "PATCH"}:
                from server.modules.products.product_category_store import (
                    update_product_category,
                )

                category = update_product_category(
                    principal,
                    unquote(category_delete.group(1)),
                    payload.get("name"),
                    payload.get("items"),
                    new_category_id=payload.get("id"),
                    is_super_admin=(
                        session is not None
                        and str(session.get("role") or "") == "super_admin"
                    ),
                )
                if category is None:
                    json_response(self, {
                        "success": False, "error": "产品分类不存在",
                    }, 404)
                    return True
                value = {
                    "success": True, "origin": "server", "category": category,
                }
            elif category_delete is not None and method == "DELETE":
                from server.modules.products.product_category_store import (
                    delete_product_category,
                )

                ok = delete_product_category(
                    principal,
                    unquote(category_delete.group(1)),
                )
                if not ok:
                    json_response(self, {
                        "success": False, "error": "用户产品分类不存在",
                    }, 404)
                    return True
                value = {"success": True, "origin": "server"}
            elif category_delete is not None:
                json_response(self, {
                    "success": False, "error": "产品分类写入方法不支持",
                }, 405)
                return True
            elif category_refresh is not None:
                json_response(self, {
                    "success": False, "error": "产品分类更新方法不支持",
                }, 405)
                return True
            elif parsed.path == "/api/product-library/product-groups":
                name = str(payload.get("name") or "").strip()
                paths = payload.get("paths")
                category_ids = payload.get("category_ids") or []
                if not name:
                    raise ValueError("产品组名称不能为空")
                if not isinstance(paths, list) or not paths:
                    raise ValueError("请选择至少一个品种路径")
                if not all(isinstance(path, str) and path.strip() for path in paths):
                    raise ValueError("产品路径必须是非空字符串")
                if not isinstance(category_ids, list) or not all(
                    isinstance(category_id, str) and category_id.strip()
                    for category_id in category_ids
                ):
                    raise ValueError("category_ids 必须是字符串数组")
                group = self.state.client_state.create_product_group(
                    principal,
                    name,
                    paths,
                    category_ids,
                    creator_kind=str(payload.get("creator_kind") or "user"),
                    creator_ref=str(payload.get("creator_ref") or ""),
                    research_refs=payload.get("research_refs"),
                )
                if group is None:
                    json_response(self, {
                        "success": False, "error": "产品组名称已存在",
                    }, 409)
                    return True
                value = {"success": True, "origin": "server", "group": group}
            elif group_subjects is not None and method == "POST":
                action = str(payload.get("action") or "")
                factor_refs = payload.get("factor_refs") or []
                factor_set_refs = payload.get("factor_set_refs") or []
                if not isinstance(factor_refs, list) or not all(
                    isinstance(item, str) for item in factor_refs
                ):
                    raise ValueError("factor_refs must be an array of references")
                if not isinstance(factor_set_refs, list) or not all(
                    isinstance(item, str) for item in factor_set_refs
                ):
                    raise ValueError("factor_set_refs must be an array of references")
                subjects = self.state.client_state.change_product_group_subjects(
                    principal,
                    unquote(group_subjects.group(1)),
                    action=action,
                    factor_refs=factor_refs,
                    factor_set_refs=factor_set_refs,
                )
                if subjects is None:
                    json_response(self, {
                        "success": False, "error": "产品组不存在",
                    }, 404)
                    return True
                value = {
                    "success": True,
                    "origin": "server",
                    "subjects": subjects,
                }
            elif group_mutation is not None and method in {"PUT", "PATCH"}:
                name = str(payload.get("name") or "").strip()
                paths = payload.get("paths")
                category_ids = payload.get("category_ids") or []
                if not name:
                    raise ValueError("产品组名称不能为空")
                if not isinstance(paths, list) or not paths:
                    raise ValueError("请选择至少一个品种路径")
                if not all(isinstance(path, str) and path.strip() for path in paths):
                    raise ValueError("产品路径必须是非空字符串")
                if not isinstance(category_ids, list) or not all(
                    isinstance(category_id, str) and category_id.strip()
                    for category_id in category_ids
                ):
                    raise ValueError("category_ids 必须是字符串数组")
                if not category_ids:
                    raise ValueError("产品组至少需要绑定一个产品分类")
                group = self.state.client_state.update_product_group(
                    principal,
                    unquote(group_mutation.group(1)),
                    name,
                    paths,
                    category_ids,
                )
                if group is None:
                    json_response(self, {
                        "success": False, "error": "产品组不存在",
                    }, 404)
                    return True
                value = {"success": True, "origin": "server", "group": group}
            elif group_mutation is not None and method == "DELETE":
                ok = self.state.client_state.delete_product_group(
                    principal, unquote(group_mutation.group(1)),
                )
                if not ok:
                    json_response(self, {
                        "success": False, "error": "产品组不存在",
                    }, 404)
                    return True
                value = {"success": True, "origin": "server"}
            else:
                value = self.state.client_state.product_price_series(payload)
        except PermissionError as exc:
            json_response(
                self, {"success": False, "error": str(exc)}, 403,
            )
            return True
        except ValueError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc)},
                int(getattr(exc, "status", 400)),
            )
            return True
        except (OSError, RuntimeError, ImportError, TypeError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        self.state.client_state._refresh_account_domain_async(principal, force=True)
        json_response(self, value)
        return True

    def _serve_test_authoring(self, parsed, *, method: str) -> bool:
        """Serve test editing state locally; never consult a worker port."""
        if not self.state.test_authoring.handles(parsed.path, method):
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and visitor is None:
            json_response(self, {
                "success": False, "error": "login required",
            }, 401)
            return True
        principal = (
            visitor.principal
            if session is None and visitor is not None
            else str(session["username"])
        )
        try:
            if method == "GET":
                response = self.state.test_authoring.get(
                    parsed.path,
                    owner=principal,
                    query=parse_qs(parsed.query, keep_blank_values=True),
                )
            else:
                payload = (
                    {
                        key: values[0]
                        for key, values in parse_qs(
                            parsed.query, keep_blank_values=True,
                        ).items()
                        if values
                    }
                    if method == "DELETE"
                    else self._json_body(1024 * 1024)
                )
                response = self.state.test_authoring.write(
                    method, parsed.path, owner=principal,
                    payload=payload,
                )
        except TestAuthoringError as exc:
            json_response(self, {
                "success": False, "error": str(exc), **exc.details,
            }, exc.status)
            return True
        except (KeyError, TypeError, ValueError) as exc:
            json_response(self, {
                "success": False, "error": str(exc),
            }, 400)
            return True
        except (OSError, RuntimeError, ImportError) as exc:
            sys.stderr.write(f"[manager] test authoring failed: {exc}\n")
            json_response(self, {
                "success": False, "error": "test authoring data is unavailable",
            }, 503)
            return True
        json_response(self, response.payload, response.status)
        return True

    def _serve_manager_application(self, parsed, *, method: str) -> bool:
        """Dispatch Manager-owned application state under one import boundary."""
        if method == "GET" and parsed.path.startswith(
            "/api/factor-library/family-sources/"
        ):
            # A missing source is fetched over the object data plane.  Keep
            # that bounded network wait outside the global first-import lock
            # so one source cannot stall unrelated catalog and authoring UI.
            return self._serve_factor_catalog(parsed)
        with self.state.application_request_lock:
            if method == "GET":
                return bool(
                    self._serve_strategy_library(parsed, method=method)
                    or
                    self._get_research_graph_catalog(parsed)
                    or
                    self._serve_report_reference(parsed)
                    or
                    self._serve_test_authoring(parsed, method=method)
                    or self._serve_product_catalog(parsed)
                    or self._serve_factor_catalog(parsed)
                )
            if method == "POST":
                return bool(
                    self._serve_strategy_library(parsed, method=method)
                    or
                    self._post_research_graph_catalog(parsed)
                    or self._serve_product_catalog_write(parsed)
                    or self._serve_factor_catalog_write(parsed, method=method)
                    or self._serve_test_authoring(parsed, method=method)
                )
            if method == "DELETE":
                return bool(
                    self._serve_strategy_library(parsed, method=method)
                    or
                    self._delete_research_graph_catalog(parsed)
                    or self._serve_product_catalog_write(parsed)
                    or self._serve_factor_catalog_write(parsed, method=method)
                    or self._serve_test_authoring(parsed, method=method)
                )
            return bool(
                self._serve_strategy_library(parsed, method=method)
                or
                self._serve_product_catalog_write(parsed)
                or self._serve_factor_catalog_write(parsed, method=method)
                or self._serve_test_authoring(parsed, method=method)
            )
