"""Compile configuration strategy bindings into the existing Run input form."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services.configuration_strategies import view
from server.services.strategy_library import StrategyLibraryService
from server.services.strategy_source_inspection import inspect_source


def compile_configuration_strategies(
    configuration: dict[str, Any],
    *,
    owner: str,
    library: StrategyLibraryService | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return one source bundle and one spec for every bound target.

    The worker still receives the established transient source bundle.  This
    adapter is the only place that turns durable library revisions or inline
    configuration objects into that execution representation.
    """
    document = configuration.get("payload") if isinstance(configuration.get("payload"), dict) else configuration
    state = view(document, include_source=True)
    temporary = {
        str(item.get("temp_ref") or ""): item
        for item in state["strategies"] if isinstance(item, dict)
    }
    sources_by_hash: dict[str, dict[str, Any]] = {}
    specs: list[dict[str, Any]] = []
    frozen_bindings: list[dict[str, Any]] = []
    for binding in state["bindings"]:
        if not isinstance(binding, dict):
            continue
        source = binding.get("source") or {}
        kind = str(source.get("kind") or "").strip().lower()
        target = str(binding.get("target_strategy_id") or "").strip()
        binding_id = str(binding.get("binding_id") or "").strip()
        if not target or not binding_id:
            raise ValueError("strategy binding requires binding_id and target_strategy_id")
        if kind == "inline":
            item = temporary.get(str(source.get("temp_ref") or ""))
            if item is None:
                raise ValueError("strategy binding references an unknown temporary strategy")
            source_code = str(item.get("source_code") or "")
            entrypoint = str(item.get("entrypoint") or "Strategy")
            inspection = inspect_source(source_code, entrypoint)
            source_hash = inspection["source_sha256"]
            origin = "inline"
            name = str(item.get("name") or target)
            requirements = deepcopy(item.get("requirements") or {})
            library_ref = ""
            revision_ref = ""
        elif kind == "library":
            if library is None:
                raise ValueError("strategy library is required for a library binding")
            library_ref = str(source.get("strategy_ref") or "").strip()
            revision_ref = str(source.get("revision_ref") or "").strip()
            revision = library.get_revision(
                library_ref, revision_ref, principal=owner, include_source=True,
            )["revision"]
            source_code = str(revision.get("source_code") or "")
            entrypoint = str(revision.get("entrypoint") or "Strategy")
            inspection = inspect_source(source_code, entrypoint)
            source_hash = inspection["source_sha256"]
            requested_hash = str(source.get("source_sha256") or "").strip()
            if requested_hash and requested_hash != source_hash:
                raise ValueError("library strategy revision source hash mismatch")
            origin = "library"
            name = library_ref
            requirements = deepcopy(revision.get("requirements") or {})
        else:
            raise ValueError("strategy binding source kind must be inline or library")
        # Content-addressed paths deduplicate identical inline and library
        # sources without losing the binding provenance in the spec.
        source_path = f"strategies/frozen/{source_hash}.py"
        sources_by_hash.setdefault(source_hash, {
            "path": source_path, "source_code": source_code,
        })
        spec: dict[str, Any] = {
            "source": f"profile:{source_path}",
            "strategy_id": target,
            "entrypoint": entrypoint,
            "requirements": requirements,
            "strategy_origin": origin,
            "binding_id": binding_id,
            "source_sha256": source_hash,
            "strategy_name": name,
        }
        if library_ref:
            spec.update({"strategy_ref": library_ref, "revision_ref": revision_ref})
        specs.append(spec)
        frozen_bindings.append({
            "binding_id": binding_id,
            "target_strategy_id": target,
            "source": {
                "kind": kind,
                **({"temp_ref": str(source.get("temp_ref") or "")} if kind == "inline" else {}),
                **({"strategy_ref": library_ref, "revision_ref": revision_ref} if kind == "library" else {}),
                "source_sha256": source_hash,
            },
        })
    return {
        "strategy_specs": specs,
        "transient_strategy_sources": list(sources_by_hash.values()),
        "strategy_bindings": frozen_bindings,
    }
