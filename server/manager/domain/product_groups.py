"""Project client-owned product groups for Web and embedded clients."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Iterable, Mapping

from tools.data.account_manage import unique_object_visibility_policy_for


def project_product_groups(
    *,
    store: Any,
    principal: str,
    profiles: Iterable[Mapping[str, Any]],
    research_records: Iterable[Mapping[str, Any]],
    product_records: Iterable[Mapping[str, Any]],
    origin: str,
) -> list[dict[str, Any]]:
    """Return owner, research, subject, and availability-aware group rows."""
    profile_index = _profile_index(profiles)
    visibility = unique_object_visibility_policy_for(
        principal,
        profile_refs=tuple(
            ref for ref in profile_index if ref.startswith("profile:")
        ),
    )
    research_index = _research_index(research_records)
    product_index = _product_index(product_records)
    visible = []
    for row in store.list_groups():
        owner_ref = str(row.get("owner_ref") or "").strip()
        if not visibility.can_view({
            "ref": str(row.get("group_ref") or ""),
            "owner_ref": owner_ref,
        }):
            continue
        definition = _object(row.get("definition_json"))
        value = dict(row)
        value.pop("definition_json", None)
        value["definition"] = definition
        value.update(_creator_projection(owner_ref, principal, profile_index, definition))
        bindings = _research_bindings(definition, research_index)
        value.update({
            "research_bindings": bindings,
            "research_refs": [item["research_ref"] for item in bindings],
            "created_for_research": bool(bindings),
        })
        products = store.list_group_products(str(value.get("group_ref") or ""))
        value["products"] = _product_memberships(
            products,
            definition.get("product_names"),
            product_index,
            origin,
        )
        subjects = store.list_group_subjects(str(value.get("group_ref") or ""))
        value["factor_refs"] = _subject_refs(subjects, "factor")
        value["factor_set_refs"] = _subject_refs(subjects, "factor_set")
        for key in (
            "paths", "selection_paths", "path_bindings", "product_names", "description",
            "category_ids",
        ):
            if key in definition:
                value[key] = definition[key]
        value["source"] = "local"
        value["catalog_origin"] = origin
        visible.append(value)
    return sorted(
        visible,
        key=lambda item: (
            str(item.get("name") or "").casefold(),
            str(item.get("group_ref") or ""),
        ),
    )


def project_account_product_groups(
    *,
    groups: Iterable[Mapping[str, Any]],
    principal: str,
    profiles: Iterable[Mapping[str, Any]],
    research_records: Iterable[Mapping[str, Any]],
    product_records: Iterable[Mapping[str, Any]],
    origin: str,
) -> list[dict[str, Any]]:
    """Project account-owned groups without selecting a service port."""
    profile_index = _profile_index(profiles)
    research_index = _research_index(research_records)
    product_index = _product_index(product_records)
    result = []
    for raw in groups:
        value = dict(raw)
        group_id = str(value.get("id") or "").strip()
        if not group_id:
            digest = sha256(str(value.get("name") or "").encode()).hexdigest()[:16]
            group_id = f"account-{digest}"
        value["group_ref"] = f"product-group:{group_id}"
        definition = {
            key: value[key]
            for key in (
                "creator", "creator_kind", "creator_ref", "research_ref",
                "research_refs",
            )
            if key in value
        }
        owner_ref = str(value.get("owner_ref") or f"user:{principal}")
        value.update(_creator_projection(
            owner_ref, principal, profile_index, definition,
        ))
        bindings = _research_bindings(definition, research_index)
        value.update({
            "owner_ref": owner_ref,
            "research_bindings": bindings,
            "research_refs": [item["research_ref"] for item in bindings],
            "created_for_research": bool(bindings),
            "products": _product_memberships(
                [], value.get("product_names"), product_index, origin,
            ),
            "factor_refs": _active_refs(value.get("factor_refs")),
            "factor_set_refs": _active_refs(value.get("factor_set_refs")),
            "source": "server",
            "catalog_origin": origin,
        })
        result.append(value)
    return sorted(
        result,
        key=lambda item: (
            str(item.get("name") or "").casefold(),
            str(item.get("group_ref") or ""),
        ),
    )


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _profile_index(values: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for value in values:
        profile_id = str(value.get("profile_id") or "").strip()
        if not profile_id:
            continue
        projected = dict(value)
        result[profile_id] = projected
        result[f"profile:{profile_id}"] = projected
    return result


def _research_index(values: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for value in values:
        projected = dict(value)
        for key in ("local_ref", "record_id", "report_id"):
            ref = str(value.get(key) or "").strip()
            if ref:
                result[ref] = projected
                if key == "record_id":
                    result[f"work-package:{ref}"] = projected
    return result


def _creator_projection(
    owner_ref: str,
    principal: str,
    profiles: Mapping[str, Mapping[str, Any]],
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    raw = definition.get("creator")
    creator = raw if isinstance(raw, dict) else {}
    explicit_kind = str(creator.get("kind") or definition.get("creator_kind") or "")
    explicit_ref = str(creator.get("ref") or definition.get("creator_ref") or "")
    profile = profiles.get(explicit_ref) or profiles.get(owner_ref)
    kind = explicit_kind if explicit_kind in {"user", "profile"} else (
        "profile" if profile is not None else "user"
    )
    if kind == "profile":
        profile_id = str((profile or {}).get("profile_id") or "")
        creator_ref = explicit_ref or owner_ref or f"profile:{profile_id}"
        title = str(
            creator.get("title")
            or (profile or {}).get("display_name")
            or profile_id
            or creator_ref
        )
    else:
        profile_id = ""
        creator_ref = explicit_ref or owner_ref or f"user:{principal}"
        title = str(creator.get("title") or principal or creator_ref)
    return {
        "creator_kind": kind,
        "creator_ref": creator_ref,
        "creator_title": title,
        "profile_ref": f"profile:{profile_id}" if profile_id else "",
    }


def _research_bindings(
    definition: Mapping[str, Any],
    research: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    raw_values = definition.get("research_refs")
    if not isinstance(raw_values, list):
        single = definition.get("research_ref")
        raw_values = [single] if single else []
    result = []
    for raw in raw_values:
        item = raw if isinstance(raw, dict) else {"research_ref": raw}
        ref = str(
            item.get("research_ref")
            or item.get("work_package_ref")
            or item.get("local_ref")
            or ""
        ).strip()
        if not ref:
            continue
        record = research.get(ref, {})
        result.append({
            "research_ref": ref,
            "title": str(item.get("title") or record.get("title") or ref),
            "profile_id": str(record.get("profile_id") or ""),
            "local_ref": str(record.get("local_ref") or ""),
        })
    return result


def _product_index(values: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for value in values:
        row = dict(value)
        for key in _product_keys(row):
            result.setdefault(key, row)
    return result


def _product_keys(value: Mapping[str, Any]) -> set[str]:
    result = {
        str(value.get(key) or "").strip()
        for key in ("product_ref", "product_path", "name", "code", "alias")
    }
    for raw in tuple(result):
        if not raw:
            continue
        result.add(raw.removeprefix("product:"))
        result.add(raw.split("/_products/")[-1])
    return {item for item in result if item}


def _product_memberships(
    memberships: Iterable[Mapping[str, Any]],
    product_names: Any,
    products: Mapping[str, Mapping[str, Any]],
    origin: str,
) -> list[dict[str, Any]]:
    pending = [dict(item) for item in memberships]
    if isinstance(product_names, list):
        known = {str(item.get("product_ref") or "") for item in pending}
        for name in product_names:
            if str(name) not in known:
                pending.append({"product_ref": str(name)})
    result = []
    seen = set()
    for membership in pending:
        raw_ref = str(
            membership.get("product_ref") or membership.get("product_name") or ""
        ).strip()
        product = next((products[key] for key in _candidate_keys(raw_ref) if key in products), None)
        identity = str((product or {}).get("product_ref") or raw_ref)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        display = str(
            (product or {}).get("name")
            or (product or {}).get("alias")
            or raw_ref.removeprefix("product:").split("/_products/")[-1]
        )
        available = product is not None
        result.append({
            **membership,
            **(dict(product) if product else {}),
            "product_ref": identity,
            "display_name": display,
            "available": available,
            "unavailable_reason": "" if available else (
                "非服务器提供，无法展示相关信息"
                if origin == "server"
                else "本地数据源未提供，无法展示相关信息"
            ),
        })
    return result


def _candidate_keys(value: str) -> tuple[str, ...]:
    plain = value.removeprefix("product:")
    leaf = plain.split("/_products/")[-1]
    return value, plain, leaf, f"product:{plain}", f"product:{leaf}"


def _subject_refs(values: Iterable[Mapping[str, Any]], kind: str) -> list[str]:
    return list(dict.fromkeys(
        str(item.get("subject_ref") or "")
        for item in values
        if item.get("subject_kind") == kind
        and item.get("state", "active") == "active"
        and str(item.get("subject_ref") or "")
    ))


def _active_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item) for item in value if isinstance(item, str) and item
    ))
