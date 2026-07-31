"""One-time migration of legacy requirement prose into typed specials."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_link_list,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_system_mutations import (
    wrap_system_requirement_component,
)


_REPORT_PREFIX = "report.requirement."


def migrate_requirement_sections(
    *,
    package_root: Path,
    branch_id: str,
    contexts: list[dict[str, Any]],
    requirement_titles: dict[str, str] | None = None,
    component_requirement_hints: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Wrap each legacy report requirement without rewriting its content."""
    titles = {
        **_requirement_titles(contexts),
        **{
            str(key).removeprefix("requirement:"): str(value)
            for key, value in (requirement_titles or {}).items()
            if str(value).strip()
        },
    }
    migrated: list[dict[str, str]] = []
    while True:
        snapshot = load_snapshot(
            package_root=package_root, branch_id=branch_id,
        )
        candidate = _next_candidate(
            snapshot,
            component_requirement_hints=component_requirement_hints or {},
        )
        if candidate is None:
            break
        component, bindings = candidate
        requirement_id = _requirement_id(bindings)
        title = titles.get(requirement_id, "").strip()
        if not title:
            raise ValueError(
                "historical report requirement has no Graph title_zh: "
                + requirement_id
            )
        _validate_subjects(bindings, requirement_id=requirement_id)
        parent_id = str(component.get("parent_id") or "")
        if not parent_id:
            raise ValueError(
                "root report chapter cannot satisfy a report requirement"
            )
        after = _previous_sibling(
            snapshot["components"], component_id=component["component_id"],
            parent_id=parent_id,
        )
        wrapper_id = _wrapper_id(
            str(component["component_id"]), requirement_id,
        )
        entry_binding = _entry_binding(
            wrapper_id=wrapper_id,
            requirement_id=requirement_id,
            title_zh=title,
        )
        existing_binding_ids = {
            str(item["binding_id"])
            for item in snapshot["bindings"]
            if item["component_id"] == component["component_id"]
        }
        transferred = [
            binding for binding in bindings
            if str(binding["binding_id"]) in existing_binding_ids
        ]
        synthesized = [
            binding for binding in bindings
            if str(binding["binding_id"]) not in existing_binding_ids
        ]
        wrap_system_requirement_component(
            package_root=package_root,
            branch_id=branch_id,
            component_id=str(component["component_id"]),
            parent_id=parent_id,
            after_component_id=after,
            wrapper={
                "component_id": wrapper_id,
                "title": title,
                "body": typed_link_list([{
                    "kind": "entry_requirement",
                    "target_ref": f"requirement:{requirement_id}",
                    "label": title,
                }]),
                "content": {
                    "schema_version": 1,
                    "requirement_id": requirement_id,
                    "migrated_component_id": str(
                        component["component_id"]
                    ),
                },
                "bindings": [entry_binding, *synthesized],
            },
            transferred_bindings=[
                {key: deepcopy(value) for key, value in binding.items()
                 if key != "component_id"}
                for binding in transferred
            ],
        )
        migrated.append({
            "component_id": str(component["component_id"]),
            "wrapper_id": wrapper_id,
            "requirement_id": requirement_id,
            "title_zh": title,
        })
    return {
        "migration": "obligation-requirement-specials-v1",
        "migrated_count": len(migrated),
        "migrated": migrated,
    }


def legacy_requirement_ids(
    *, package_root: Path, branch_id: str,
) -> set[str]:
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    components = {
        str(item["component_id"]): item
        for item in snapshot["components"]
    }
    return {
        str(item["target_ref"]).removeprefix(_REPORT_PREFIX)
        for item in snapshot["bindings"]
        if (
            item.get("kind") == "report_requirement"
            and str(item.get("target_ref") or "").startswith(
                _REPORT_PREFIX
            )
            and not (
                components[str(item["component_id"])]["kind"] == "special"
                and components[str(item["component_id"])][
                    "display_kind"
                ] == "obligation_requirement"
            )
        )
    }


def _next_candidate(
    snapshot: dict[str, Any],
    *,
    component_requirement_hints: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    components = {
        str(item["component_id"]): item
        for item in snapshot["components"]
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for binding in snapshot["bindings"]:
        if (
            binding.get("kind") == "report_requirement"
            and str(binding.get("target_ref") or "").startswith(
                _REPORT_PREFIX
            )
        ):
            grouped.setdefault(str(binding["component_id"]), []).append(
                binding
            )
    for component_id, bindings in grouped.items():
        component = components[component_id]
        if (
            component["kind"] == "special"
            and component["display_kind"] == "obligation_requirement"
        ):
            _validate_migrated_special(
                snapshot, component=component, bindings=bindings,
            )
            continue
        return component, bindings
    for component_id, hint in component_requirement_hints.items():
        component = components.get(component_id)
        if component is None:
            raise ValueError(
                "historical requirement mapping references an absent "
                f"component: {component_id}"
            )
        requirement_id = str(hint.get("requirement_id") or "")
        if _is_wrapped_requirement(
            snapshot,
            component=component,
            requirement_id=requirement_id,
        ):
            continue
        return component, [_mapped_report_binding(
            component_id=component_id,
            hint=hint,
        )]
    return None


def _is_wrapped_requirement(
    snapshot: dict[str, Any],
    *,
    component: dict[str, Any],
    requirement_id: str,
) -> bool:
    parent_id = str(component.get("parent_id") or "")
    parent = next((
        item for item in snapshot["components"]
        if item["component_id"] == parent_id
    ), None)
    if not parent or not (
        parent["kind"] == "special"
        and parent["display_kind"] == "obligation_requirement"
    ):
        return False
    expected = f"requirement:{requirement_id}"
    return any(
        item["component_id"] == parent_id
        and item["kind"] == "entry_requirement"
        and item["target_ref"] == expected
        for item in snapshot["bindings"]
    )


def _mapped_report_binding(
    *,
    component_id: str,
    hint: dict[str, str],
) -> dict[str, Any]:
    requirement_id = str(hint.get("requirement_id") or "")
    subject_ref = str(hint.get("subject_ref") or "")
    content_kind = str(hint.get("content_kind") or "")
    if not requirement_id or not subject_ref or not content_kind:
        raise ValueError(
            "historical requirement mapping requires requirement_id, "
            "subject_ref, and content_kind"
        )
    target_ref = f"report.requirement.{requirement_id}"
    token = hashlib.sha256(
        f"{component_id}\x1f{target_ref}".encode()
    ).hexdigest()[:40]
    return {
        "binding_id": f"history-report-requirement-{token}",
        "kind": "report_requirement",
        "target_ref": target_ref,
        "label": "报告义务",
        "data": {
            "report_requirement_id": target_ref,
            "subject_ref": subject_ref,
            "content_kind": content_kind,
        },
    }


def _validate_migrated_special(
    snapshot: dict[str, Any],
    *,
    component: dict[str, Any],
    bindings: list[dict[str, Any]],
) -> None:
    requirement_id = _requirement_id(bindings)
    expected = f"requirement:{requirement_id}"
    if not any(
        item.get("component_id") == component["component_id"]
        and item.get("kind") == "entry_requirement"
        and item.get("target_ref") == expected
        for item in snapshot["bindings"]
    ):
        raise ValueError(
            "obligation_requirement special has no matching typed link: "
            + str(component["component_id"])
        )


def _requirement_id(bindings: list[dict[str, Any]]) -> str:
    values = {
        str(item["target_ref"]).removeprefix(_REPORT_PREFIX)
        for item in bindings
    }
    if len(values) != 1:
        raise ValueError(
            "one historical component cannot cover multiple report "
            "requirement categories"
        )
    return next(iter(values))


def _validate_subjects(
    bindings: list[dict[str, Any]], *, requirement_id: str,
) -> None:
    expected = f"requirement:{requirement_id}"
    for binding in bindings:
        subject = str((binding.get("data") or {}).get("subject_ref") or "")
        if not subject:
            raise ValueError(
                "historical report requirement has no frozen subject"
            )
        if subject.startswith("requirement:") and subject != expected:
            raise ValueError(
                "historical report requirement subject does not match its "
                f"Graph category: {binding['target_ref']} -> {subject}"
            )


def _requirement_titles(
    contexts: list[dict[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for context in contexts:
        for item in context.get("requirement_presentations") or []:
            requirement_id = str(
                item.get("requirement_id") or ""
            ).removeprefix("requirement:")
            title = str(item.get("title_zh") or "").strip()
            if requirement_id and title:
                result[requirement_id] = title
    return result


def _previous_sibling(
    components: list[dict[str, Any]],
    *,
    component_id: str,
    parent_id: str,
) -> str | None:
    siblings = [
        str(item["component_id"])
        for item in components
        if str(item.get("parent_id") or "") == parent_id
    ]
    try:
        index = siblings.index(component_id)
    except ValueError as exc:
        raise ValueError(
            "historical report component is absent from its parent"
        ) from exc
    return None if index == 0 else siblings[index - 1]


def _wrapper_id(component_id: str, requirement_id: str) -> str:
    token = hashlib.sha256(
        f"{component_id}\x1f{requirement_id}".encode()
    ).hexdigest()[:40]
    return f"obligation-requirement-{token}"


def _entry_binding(
    *, wrapper_id: str, requirement_id: str, title_zh: str,
) -> dict[str, Any]:
    token = hashlib.sha256(
        f"{wrapper_id}\x1f{requirement_id}".encode()
    ).hexdigest()[:40]
    return {
        "binding_id": f"history-requirement-{token}",
        "kind": "entry_requirement",
        "target_ref": f"requirement:{requirement_id}",
        "label": title_zh,
        "data": {
            "role": "obligation_requirement",
            "title_zh": title_zh,
        },
    }
