from __future__ import annotations

import os

from tools.data.sqlite.account_manager import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config as _delete_factor_param_config,
    delete_factor_family_configs as _delete_factor_family_configs,
    delete_scope as _delete_scope,
    ensure_account_manager_sqlite_store,
    factor_research_config_hash as _factor_research_config_hash,
    delete_factor_research_run as _delete_factor_research_run,
    list_factor_research_runs as _list_factor_research_runs,
    ensure_scope_exists as _ensure_scope_exists,
    list_all_factor_param_aliases_across_scopes as _list_all_aliases_across_scopes,
    list_factor_param_config_aliases as _list_factor_param_config_aliases,
    list_factor_param_config_scopes as _list_factor_param_config_scopes,
    list_factor_family_dependency_configs as _list_factor_family_dependency_configs,
    load_factor_param_config as _load_factor_param_config,
    load_product_groups as _load_product_groups,
    load_product_categories as _load_product_categories,
    list_factor_sets as _list_factor_sets,
    get_factor_set as _get_factor_set,
    normalize_product_group as _normalize_product_group,
    rename_scope as _rename_scope,
    save_factor_research_run as _save_factor_research_run,
    save_factor_param_config as _save_factor_param_config,
    save_product_groups as _save_product_groups,
    save_product_categories as _save_product_categories,
    save_factor_set as _save_factor_set,
    delete_factor_set as _delete_factor_set,
)
from tools.data.sqlite.account_manager.domain_sync import (
    replace_entities as _replace_domain_entities,
)

ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ORG_ADMIN = 'org_admin'
ROLE_LEVEL_ADMIN = 'level_admin'
ROLE_DEVELOPER = 'developer'
ROLE_USER = 'user'


def account_display_name(account: dict | None) -> str:
    if not account:
        return ""
    alias = str(account.get('alias') or '').strip()
    if alias:
        return alias
    username = str(account.get('username') or '').strip()
    parts = username.rsplit('@', 1)
    if len(parts) == 2 and parts[1].isdigit() and '@' in parts[0]:
        return parts[0].split('@', 1)[1]
    return username


def get_account(username: str | None) -> dict | None:
    """Return only the verified Keycloak identity for the current request."""
    principal = str(username or "").strip()
    if not principal:
        return None
    identity = _verified_keycloak_request_identity()
    if not identity or str(identity.get("username") or "").strip() != principal:
        return None
    return _project_keycloak_account_authority(dict(identity))


def _verified_keycloak_request_identity() -> dict | None:
    try:
        from flask import g, has_request_context
        if not has_request_context():
            from server.identity.request_context import current_verified_identity
            verified = current_verified_identity()
            return verified[1] if verified else None
        identity = getattr(g, "keycloak_user_session", None)
        if not isinstance(identity, dict):
            from server.services.session_runtime import _keycloak_request_session
            identity = _keycloak_request_session()
        return identity if isinstance(identity, dict) else None
    except Exception:
        return None


def _account_principal(account: object) -> str:
    if isinstance(account, dict):
        return str(account.get("username") or account.get("name") or "").strip()
    return str(getattr(account, "name", "") or "").strip()


def _keycloak_roles_for_account(account: object) -> set[str]:
    """Return roles from the verified current request, failing closed."""
    try:
        identity = _verified_keycloak_request_identity()
        if not isinstance(identity, dict):
            return set()
        principal = _account_principal(account)
        if principal != str(identity.get("username") or "").strip():
            return set()
        return {str(role) for role in identity.get("keycloak_roles", ()) if role}
    except Exception:
        # Authorization helpers fail closed if the request identity cannot be
        # resolved; callers must not fall back to the SQLite role snapshot.
        return set()


def _keycloak_groups_for_account(account: object) -> set[str]:
    try:
        identity = _verified_keycloak_request_identity()
        if not isinstance(identity, dict):
            return set()
        if _account_principal(account) != str(identity.get("username") or "").strip():
            return set()
        return {str(path) for path in identity.get("keycloak_groups", ()) if path}
    except Exception:
        return set()


def _role_for_keycloak_roles(roles: set[str], groups: set[str] | None = None) -> str:
    if "admin_console:manage" in roles:
        return ROLE_SUPER_ADMIN
    from server.identity.realm_groups import administrative_group_role
    scoped_role = administrative_group_role(tuple(groups or ()))
    if scoped_role in {ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN}:
        return scoped_role
    if "factor:develop" in roles:
        return ROLE_DEVELOPER
    return ROLE_USER


def _project_keycloak_account_authority(account: dict | None) -> dict | None:
    if account is None:
        return None
    roles = _keycloak_roles_for_account(account)
    if roles is None:
        return account
    groups = _keycloak_groups_for_account(account) or set()
    projected = dict(account)
    role = _role_for_keycloak_roles(roles, groups)
    projected.update({
        "role": role,
        "is_admin": role == ROLE_SUPER_ADMIN,
        "is_developer": role == ROLE_DEVELOPER,
        "keycloak_roles": tuple(sorted(roles)),
        "keycloak_groups": tuple(sorted(groups)),
    })
    return projected


def is_super_admin_account(account: dict | None) -> bool:
    return "admin_console:manage" in _keycloak_roles_for_account(account)


def is_org_admin_account(account: dict | None) -> bool:
    keycloak_roles = _keycloak_roles_for_account(account)
    groups = _keycloak_groups_for_account(account)
    return _role_for_keycloak_roles(keycloak_roles, groups) in {
        ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN,
    }


def is_level_admin_account(account: dict | None) -> bool:
    keycloak_roles = _keycloak_roles_for_account(account)
    groups = _keycloak_groups_for_account(account)
    return _role_for_keycloak_roles(keycloak_roles, groups) in {
        ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN,
    }


def is_any_admin_account(account: dict | None) -> bool:
    keycloak_roles = _keycloak_roles_for_account(account)
    # These helpers gate Manager-wide entitlements and operations. Scoped
    # administrators are authorized by Keycloak against the target object.
    return "admin_console:manage" in keycloak_roles


def is_developer_account(account: dict | None) -> bool:
    return "factor:develop" in _keycloak_roles_for_account(account)


def direct_subordinate_accounts_for(username: str | None) -> list:
    """Compatibility projection of the current Keycloak-managed subtree.

    Realm Group nesting is the sole hierarchy source. This function returns a
    directory list for callers that need candidate owners; protected object
    access must still be checked by Keycloak Authorization Services.
    """
    from server.identity.keycloak_directory import managed_users_for_verified_request

    return managed_users_for_verified_request(username)


def unique_object_visibility_policy_for(
    username: str | None,
    *,
    profile_refs: list[str] | tuple[str, ...] = (),
    shared_object_refs: list[str] | tuple[str, ...] = (),
):
    """Build the one object-visibility policy used by every catalog domain."""
    from tools.data.types.object_visibility import UniqueObjectVisibilityPolicy

    principal = str(username or "").strip()
    if not principal:
        return UniqueObjectVisibilityPolicy(own_owner_refs=())
    own_refs = {
        f"user:{principal}",
        f"principal:{principal}",
        *(str(value).strip() for value in profile_refs if str(value).strip()),
    }
    return UniqueObjectVisibilityPolicy(
        own_owner_refs=own_refs,
        # Hierarchy membership is not a grant to another user's objects.
        # Resource-specific sharing is evaluated by Keycloak FGAP.
        direct_subordinate_owner_refs=(),
        shared_object_refs=shared_object_refs,
    )


def load_product_groups(username: str) -> list:
    ensure_account_manager_sqlite_store()
    from server.jobs.storage.couchdb_authority import libraries_read_enabled

    if libraries_read_enabled():
        try:
            from server.jobs.storage.couchdb_library_reader import CouchDBLibraryReader
            from server.jobs.storage.couchdb_reports import CouchDBObjectStore
            import settings as Settings

            url = str(os.environ.get("FACTORTESTER_COUCHDB_URL") or "").strip()
            if url:
                reader = CouchDBLibraryReader(CouchDBObjectStore(
                    url, str(os.environ.get("FACTORTESTER_COUCHDB_DB") or "ft_objects"),
                ))
                return reader.product_groups(username)
        except Exception:
            pass
    return _load_product_groups(username)


def save_product_groups(username: str, groups: list) -> None:
    ensure_account_manager_sqlite_store()
    _save_product_groups(username, groups)
    from server.jobs.storage.couchdb_authority import libraries_write_enabled

    if libraries_write_enabled():
        try:
            from server.jobs.storage.couchdb_library_reader import CouchDBLibraryWriter
            from server.jobs.storage.couchdb_reports import CouchDBObjectStore

            url = str(os.environ.get("FACTORTESTER_COUCHDB_URL") or "").strip()
            if url:
                CouchDBLibraryWriter(CouchDBObjectStore(
                    url, str(os.environ.get("FACTORTESTER_COUCHDB_DB") or "ft_objects"),
                )).replace_product_groups(username, groups)
        except Exception:
            pass
    _replace_domain_entities(
        username, "product_group", groups, id_key="id",
    )


def load_product_categories(username: str) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _load_product_categories(username)


def save_product_categories(username: str, categories: list[dict]) -> None:
    ensure_account_manager_sqlite_store()
    _save_product_categories(username, categories)
    _replace_domain_entities(
        username, "product_category", categories, id_key="id",
    )


def list_factor_sets(username: str) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _list_factor_sets(username)


def get_factor_set(username: str, target_ref: str) -> dict | None:
    ensure_account_manager_sqlite_store()
    return _get_factor_set(username, target_ref)


def save_factor_set(username: str, value: dict) -> dict:
    ensure_account_manager_sqlite_store()
    return _save_factor_set(username, value)


def delete_factor_set(username: str, target_ref: str) -> bool:
    ensure_account_manager_sqlite_store()
    return _delete_factor_set(username, target_ref)


def normalize_product_group(product_group: str | None) -> str:
    return _normalize_product_group(product_group)


def load_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> dict | None:
    ensure_account_manager_sqlite_store()
    return _load_factor_param_config(username, ff_alias, scope_key)


def save_factor_param_config(
    username: str,
    ff_alias: str,
    params_list: list,
    scope_key: str = DEFAULT_SCOPE_KEY,
    *,
    metadata: dict | None = None,
    resolved_factors: list[dict] | None = None,
) -> dict:
    ensure_account_manager_sqlite_store()
    result = _save_factor_param_config(
        username, ff_alias, params_list, scope_key, metadata=metadata,
        **({'resolved_factors': resolved_factors} if resolved_factors is not None else {}),
    )
    _enqueue_domain_entity(
        username,
        "factor_param_config",
        f"{scope_key}:{ff_alias}",
        result,
    )
    return result


def delete_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> bool:
    ensure_account_manager_sqlite_store()
    deleted = _delete_factor_param_config(username, ff_alias, scope_key)
    if deleted:
        _enqueue_domain_entity(
            username,
            "factor_param_config",
            f"{scope_key}:{ff_alias}",
            {},
            deleted=True,
        )
    return deleted


def delete_factor_family_configs(
    ff_alias: str, *, username: str | None = None,
) -> dict[str, int]:
    """Delete a family's registrations and publish matching tombstones."""
    ensure_account_manager_sqlite_store()
    deleted = _delete_factor_family_configs(ff_alias, username=username)
    return {
        "config_count": len(deleted),
        "factor_count": sum(item["factor_count"] for item in deleted),
    }


def list_factor_family_dependency_configs(
    ff_alias: str, *, owner_ref: str,
) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _list_factor_family_dependency_configs(
        ff_alias, owner_ref=owner_ref,
    )


def list_factor_param_config_aliases(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> list[str]:
    ensure_account_manager_sqlite_store()
    return _list_factor_param_config_aliases(username, scope_key)


def list_factor_param_config_scopes(username: str) -> list[str]:
    ensure_account_manager_sqlite_store()
    return _list_factor_param_config_scopes(username)


def list_all_factor_param_aliases_across_scopes(username: str) -> dict[str, list[str]]:
    ensure_account_manager_sqlite_store()
    return _list_all_aliases_across_scopes(username)


def ensure_scope_exists(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> str:
    ensure_account_manager_sqlite_store()
    return _ensure_scope_exists(username, scope_key)


def rename_scope(username: str, old_scope_key: str, new_scope_key: str) -> bool:
    ensure_account_manager_sqlite_store()
    aliases = _list_factor_param_config_aliases(username, old_scope_key)
    renamed = _rename_scope(username, old_scope_key, new_scope_key)
    if renamed:
        for alias in aliases:
            _enqueue_domain_entity(
                username, "factor_param_config", f"{old_scope_key}:{alias}",
                {}, deleted=True,
            )
            value = _load_factor_param_config(username, alias, new_scope_key)
            if isinstance(value, dict):
                _enqueue_domain_entity(
                    username, "factor_param_config", f"{new_scope_key}:{alias}",
                    value,
                )
    return renamed


def delete_scope(username: str, scope_key: str) -> bool:
    ensure_account_manager_sqlite_store()
    aliases = _list_factor_param_config_aliases(username, scope_key)
    deleted = _delete_scope(username, scope_key)
    if deleted:
        for alias in aliases:
            _enqueue_domain_entity(
                username, "factor_param_config", f"{scope_key}:{alias}",
                {}, deleted=True,
            )
    return deleted


def factor_research_config_hash(config: dict | None) -> str:
    return _factor_research_config_hash(config)


def save_factor_research_run(
    username: str,
    *,
    ff_alias: str,
    factor_alias: str,
    start_date: str,
    end_date: str,
    test_type: str,
    metrics: dict,
    product_group: str = "",
    factor_source: str = "",
    config: dict | None = None,
    config_hash_value: str | None = None,
    report_path: str = "",
    artifact_path: str = "",
    note: str = "",
    sample_role: str = "",
    regime_label: str = "",
    slice_name: str = "",
    run_id: str | None = None,
) -> dict:
    ensure_account_manager_sqlite_store()
    result = _save_factor_research_run(
        username,
        ff_alias=ff_alias,
        factor_alias=factor_alias,
        start_date=start_date,
        end_date=end_date,
        test_type=test_type,
        metrics=metrics,
        product_group=product_group,
        factor_source=factor_source,
        config=config,
        config_hash_value=config_hash_value,
        report_path=report_path,
        artifact_path=artifact_path,
        note=note,
        sample_role=sample_role,
        regime_label=regime_label,
        slice_name=slice_name,
        run_id=run_id,
    )
    _enqueue_domain_entity(
        username,
        "factor_research_run",
        str(result.get("run_id") or run_id or ""),
        result,
    )
    return result


def list_factor_research_runs(
    username: str,
    *,
    ff_alias: str | None = None,
    factor_alias: str | None = None,
    product_group: str | None = None,
    test_type: str | None = None,
    sample_role: str | None = None,
    regime_label: str | None = None,
    slice_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    overlap: bool = True,
    min_metrics: dict[str, float] | None = None,
    max_metrics: dict[str, float] | None = None,
    order_by_metric: str | None = None,
    descending: bool = True,
    limit: int | None = None,
) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _list_factor_research_runs(
        username,
        ff_alias=ff_alias,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type=test_type,
        sample_role=sample_role,
        regime_label=regime_label,
        slice_name=slice_name,
        start_date=start_date,
        end_date=end_date,
        overlap=overlap,
        min_metrics=min_metrics,
        max_metrics=max_metrics,
        order_by_metric=order_by_metric,
        descending=descending,
        limit=limit,
    )


def delete_factor_research_run(username: str, run_id: str) -> bool:
    ensure_account_manager_sqlite_store()
    deleted = _delete_factor_research_run(username, run_id)
    if deleted:
        _enqueue_domain_entity(
            username, "factor_research_run", run_id, {}, deleted=True,
        )
    return deleted
