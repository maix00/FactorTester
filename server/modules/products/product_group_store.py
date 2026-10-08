"""Product group storage helpers backed by SQLite."""

from __future__ import annotations

import re
import time
import uuid
from hashlib import sha1

from server.modules.products.product_category_paths import (
    canonicalize_product_paths,
    infer_category_ids,
    normalize_category_selection_paths,
)
from server.modules.products.product_category_store import (
    list_product_categories,
    migrate_owned_category_id,
    migrate_owned_category_path,
)
from server.modules.products.product_path_selection import resolve_selection_products
from tools.data.account_manage import load_product_groups as _load_product_groups
from tools.data.account_manage import save_product_groups as _save_product_groups
from tools.data.sqlite.account_manager.domain_sync import enqueue_entity
from tools.products.product_path_selection import ProductPathSelection


def _resolve_group_products(paths: list) -> list:
    from server.modules.shared.price_services import cached_product_tree

    tree = cached_product_tree().tree
    _, products = resolve_selection_products(paths, tree)
    return [getattr(product, "name", str(product)) for product in products]


def product_group_definition(group: dict, username: str) -> dict:
    """Read legacy editor paths as the definition; never expand on a list read.

    Older rows stored expanded paths alongside selection_paths. The latter
    retains the authored category references and takes precedence. This is a
    read projection; only an explicit edit persists its normalized definition.
    """
    value = dict(group)
    value.setdefault("id", _legacy_group_id(value.get("name")))
    raw = value.get("selection_paths")
    if not isinstance(raw, list):
        raw = value.get("paths") or []
    paths = [migrate_owned_category_path(username, item) for item in raw]
    # No category-tree construction or membership resolution during lists.
    # Explicit create/edit normalizes references; submission resolves them.
    value["paths"] = paths
    value["selection_paths"] = list(paths)  # Existing editor API projection.
    value["category_ids"] = [
        migrate_owned_category_id(username, item)
        for item in _category_ids(value.get("category_ids"))
    ]
    for key in ("product_names", "product_count", "products"):
        value.pop(key, None)
    return _enrich_group(value)


def load_product_groups(username: str) -> list:
    return [product_group_definition(group, username)
            for group in _load_product_groups(username)]


def load_account_domain_product_groups(username: str) -> list[dict]:
    """Read the owner's non-deleted groups from the shared domain mirror."""
    import settings as Settings
    from server.manager.storage.account_domain.local import LocalAccountDomainStore

    rows = LocalAccountDomainStore(Settings.CACHE_DB_PATH).list_entities(
        principal=username,
        entity_type="product_group",
        include_shared=False,
        include_deleted=False,
    )
    return [
        dict(payload)
        for row in rows
        if isinstance(row, dict)
        and isinstance((payload := row.get("payload")), dict)
    ]


def load_authoritative_product_groups(
    username: str,
    *,
    domain_rows: list[dict] | tuple[dict, ...] | None = None,
) -> list[dict]:
    """Return one owner catalog, preferring domain-mirror rows by stable ID."""
    merged: dict[str, dict] = {}
    for group in load_product_groups(username):
        if not isinstance(group, dict):
            continue
        key = str(group.get("id") or group.get("name") or "").strip()
        if key:
            merged[key] = group
    if domain_rows is None:
        import settings as Settings
        from server.manager.storage.account_domain.local import (
            LocalAccountDomainStore,
        )

        domain_rows = LocalAccountDomainStore(
            Settings.CACHE_DB_PATH,
        ).list_entities(
            principal=username,
            entity_type="product_group",
            include_shared=False,
            include_deleted=True,
        )
    owners: dict[str, str] = {}
    for row in domain_rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        key = str(
            (payload or {}).get("id") if isinstance(payload, dict) else ""
        ).strip() or str(row.get("entity_id") or "").strip()
        if not key:
            continue
        if row.get("deleted"):
            merged.pop(key, None)
        elif isinstance(payload, dict):
            merged[key] = dict(payload)
            owners[key] = str(row.get("principal") or username)
    return [product_group_definition(group, owners.get(key, username))
            for key, group in merged.items()]


def save_product_groups(username: str, groups: list) -> None:
    # Only authored rules cross servers. Membership is a submission-time fact.
    definitions = []
    for group in groups:
        value = dict(group)
        value["paths"] = list(value.get("selection_paths") or value.get("paths") or [])
        for key in ("selection_paths", "path_bindings", "path_count", "product_names",
                    "product_count", "products", "definition_error"):
            value.pop(key, None)
        definitions.append(value)
    _save_product_groups(username, definitions)


def find_group_by_name(groups: list, name: str) -> int:
    for i, group in enumerate(groups):
        if group.get("name") == name:
            return i
    return -1


def find_group_by_paths(groups: list, paths: list) -> dict | None:
    wanted = {str(path) for path in paths if str(path).strip()}
    for group in groups:
        current = {str(path) for path in group.get("paths", []) if str(path).strip()}
        if current == wanted:
            return group
    return None


def product_group_to_path_selection(
    group: dict,
    *,
    selection_id: str | None = None,
    page_uuid: str = "",
) -> ProductPathSelection:
    """Build the backend product-path selection that corresponds to one template row."""
    name = str(group.get("name") or group.get("product_group") or "").strip()
    if not name:
        raise AssertionError("产品组模板缺少名称")
    return ProductPathSelection.from_product_group_template(
        selection_id or str(group.get("id") or name),
        group,
        page_uuid=page_uuid,
    )


def _enrich_group(group: dict) -> dict:
    paths = group.get("paths", [])
    group["path_count"] = len(paths)
    selection_paths = group.get("selection_paths") or paths
    group["selection_paths"] = list(selection_paths)
    group["path_bindings"] = product_group_path_bindings(selection_paths)
    return group


def product_group_path_bindings(paths: object) -> list[dict[str, object]]:
    """Project a group's flat signed paths into its two fixed semantic rows.

    A product group has exactly two path slots.  The labels are part of the
    domain contract rather than user-created category labels: positive paths
    form the initial membership and negative paths subtract exceptions.
    """
    positive: list[str] = []
    negative: list[str] = []
    for raw in paths if isinstance(paths, list) else []:
        value = str(raw or "").strip()
        if not value:
            continue
        if value.startswith("-"):
            path = value[1:].strip()
            if path:
                negative.append(path)
        else:
            positive.append(value)
    return [
        {"id": "positive", "label": "正路径", "paths": positive},
        {"id": "negative", "label": "负路径", "paths": negative},
    ]


def create_product_group(
    username: str,
    name: str,
    paths: list,
    *,
    creator_kind: str = "user",
    creator_ref: str = "",
    research_refs: list[str] | None = None,
    category_ids: list[str] | None = None,
) -> dict | None:
    name = name.strip()
    if not name:
        return None
    groups = load_product_groups(username)
    if find_group_by_name(groups, name) >= 0:
        return None
    normalized_category_ids = _validate_category_ids(username, category_ids)
    selection_paths = normalize_category_selection_paths(
        paths, username=username, category_ids=normalized_category_ids,
    )
    creator = _creator_metadata(
        username,
        creator_kind=creator_kind,
        creator_ref=creator_ref,
    )
    group = {
        "id": f"pg_{uuid.uuid4().hex[:12]}",
        "name": name,
        "paths": selection_paths,
        "selection_paths": selection_paths,
        "category_ids": normalized_category_ids,
        **creator,
        "research_refs": _research_refs(research_refs),
        "factor_refs": [],
        "factor_set_refs": [],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    groups.append(_enrich_group(group))
    save_product_groups(username, groups)
    return group


def update_product_group(
    username: str,
    name: str,
    paths: list | None = None,
    category_ids: list[str] | None = None,
    *,
    new_name: str | None = None,
) -> dict | None:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return None
    group = groups[idx]
    requested_name = str(new_name if new_name is not None else name).strip()
    if not requested_name:
        raise ValueError("产品组名称不能为空")
    if requested_name != str(group.get("name") or "") and (
        find_group_by_name(groups, requested_name) >= 0
    ):
        raise ValueError("产品组名称已存在")
    group["name"] = requested_name
    next_category_ids = (
        _validate_category_ids(username, category_ids)
        if category_ids is not None
        else _category_ids(group.get("category_ids"))
    )
    if paths is not None:
        group["selection_paths"] = normalize_category_selection_paths(
            paths, username=username, category_ids=next_category_ids,
        )
        group["paths"] = list(group["selection_paths"])
    group["category_ids"] = next_category_ids
    if paths is not None or category_ids is not None:
        groups[idx] = _enrich_group(group)
    groups[idx]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_product_groups(username, groups)
    return groups[idx]


def product_group_subjects(username: str, product_group_ref: str) -> dict | None:
    group = _group_by_ref(load_product_groups(username), product_group_ref)
    if group is None:
        return None
    return {
        "product_group_ref": f"product-group:{group['id']}",
        "product_group_id": group["id"],
        "product_group_name": group.get("name") or "",
        "factor_refs": list(group.get("factor_refs") or []),
        "factor_set_refs": list(group.get("factor_set_refs") or []),
    }


def change_product_group_subjects(
    username: str,
    product_group_ref: str,
    *,
    action: str,
    factor_refs: list[str],
    factor_set_refs: list[str],
) -> dict | None:
    """Add or remove subject references without changing the subject objects."""
    if action not in {"add", "remove"}:
        raise ValueError("product group subject action must be add or remove")
    factors = _subject_refs(factor_refs, key="factor_refs")
    factor_sets = _subject_refs(factor_set_refs, key="factor_set_refs")
    if not factors and not factor_sets:
        raise ValueError("at least one factor or factor-set reference is required")
    groups = load_product_groups(username)
    group = _group_by_ref(groups, product_group_ref)
    if group is None:
        return None
    if action == "add":
        group["factor_refs"] = sorted({*(group.get("factor_refs") or []), *factors})
        group["factor_set_refs"] = sorted({
            *(group.get("factor_set_refs") or []), *factor_sets,
        })
    else:
        group["factor_refs"] = sorted(set(group.get("factor_refs") or []) - set(factors))
        group["factor_set_refs"] = sorted(
            set(group.get("factor_set_refs") or []) - set(factor_sets)
        )
    group["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_product_groups(username, groups)
    return product_group_subjects(username, product_group_ref)


def delete_product_group(username: str, name: str) -> bool:
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, name)
    if idx < 0:
        return False
    group_id = str(groups[idx].get("id") or "").strip()
    groups.pop(idx)
    save_product_groups(username, groups)
    if group_id:
        enqueue_entity(username, "product_group", group_id, {}, deleted=True)
    return True


def _legacy_group_id(name: object) -> str:
    raw = str(name or "").strip() or "unnamed"
    return f"pg_{sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _category_ids(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item).strip() for item in value if str(item).strip()
    ))


def _validate_category_ids(username: str, value: object) -> list[str]:
    ids = _category_ids(value)
    definitions = {
        str(item.get("id") or "") for item in list_product_categories(username)
    }
    unknown = sorted(set(ids) - definitions)
    if unknown:
        raise ValueError("产品分类不存在: " + ", ".join(unknown))
    return ids


def _group_by_ref(groups: list, product_group_ref: str) -> dict | None:
    prefix = "product-group:"
    if not isinstance(product_group_ref, str) or not product_group_ref.startswith(prefix):
        raise ValueError("product_group_ref must be a stable product-group reference")
    group_id = product_group_ref.removeprefix(prefix).strip()
    if not group_id:
        raise ValueError("product_group_ref is empty")
    return next(
        (group for group in groups if str(group.get("id") or "") == group_id),
        None,
    )


def _subject_refs(value: object, *, key: str) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 4096:
        raise ValueError(f"{key} must be a bounded array")
    prefixes = ("factor:",) if key == "factor_refs" else ("factor-set:",)
    if not all(
        isinstance(item, str) and item.startswith(prefixes)
        for item in value
    ):
        raise ValueError(f"{key} contains an invalid reference")
    return sorted(set(value))


def _creator_metadata(
    username: str,
    *,
    creator_kind: str,
    creator_ref: str,
) -> dict[str, str]:
    kind = str(creator_kind or "user").strip()
    reference = str(creator_ref or "").strip()
    if kind == "user":
        expected = f"user:{username}"
        if reference not in {"", username, expected}:
            raise ValueError("user creator_ref must identify the logged-in user")
        return {"creator_kind": "user", "creator_ref": expected}
    if kind != "profile":
        raise ValueError("creator_kind must be user or profile")
    if not re.fullmatch(r"profile:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", reference):
        raise ValueError("profile creator_ref is invalid")
    return {"creator_kind": "profile", "creator_ref": reference}


def _research_refs(value: object) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("research_refs must be a bounded array")
    result = []
    for item in value:
        reference = str(item or "").strip()
        prefix, separator, identifier = reference.partition(":")
        if (
            len(reference) > 512
            or not separator
            or prefix not in {"research", "report", "report-workspace"}
            or not identifier
            or not re.fullmatch(r"[a-z][a-z0-9_-]*:[^\s]+", reference)
        ):
            raise ValueError("research_refs contains an invalid stable reference")
        result.append(reference)
    return sorted(set(result))


def rename_product_group(username: str, old_name: str, new_name: str) -> dict | None:
    new_name = new_name.strip()
    if not new_name:
        return None
    groups = load_product_groups(username)
    idx = find_group_by_name(groups, old_name)
    if idx < 0:
        return None
    if old_name != new_name and find_group_by_name(groups, new_name) >= 0:
        return None
    groups[idx]["name"] = new_name
    groups[idx]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    save_product_groups(username, groups)
    return groups[idx]


def reorder_product_groups(username: str, names: list) -> bool:
    groups = load_product_groups(username)
    group_by_name = {group.get("name"): group for group in groups}
    reordered = [group_by_name[name] for name in names if name in group_by_name]
    if len(reordered) != len(groups):
        return False
    save_product_groups(username, reordered)
    return True
