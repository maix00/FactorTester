"""One-time migration of editable configurations to formula identities.

Historical RunSpecs and Jobs are deliberately outside this migration.  They
remain immutable and cannot be restored into an editable workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

# Keep the explicit migration executable both as ``python -m`` and as a
# repository-relative script.  Operators commonly invoke one-time migrations
# directly while connected through the maintenance tunnel.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

import settings as Settings
from tools.factors.formula_identity import (
    freeze_factor_identity,
    require_frozen_factor,
)
from tools.factors.factor_set_identity import (
    freeze_factor_set_identity,
    require_frozen_factor_set,
)

CONFIGURATION_SCHEMA_VERSION = 2
_POSITIONAL_ALIAS = re.compile(r":\d+$")
_REMOVED_FACTOR_FIELDS = {
    "factor_git_commit",
    "git_commit",
    "git_blob",
    "relative_path",
    "factor_family_ref",
}
_IDENTITY_FIELDS = {
    "factor_ref",
    "target_ref",
    "factor_owner_ref",
    "owner_ref",
    "factor_family_alias",
    "family_alias",
    "family",
    "factor_alias",
    "alias",
    "factor_params",
    "params",
    "family_formula_fingerprint",
    "self_formula_fingerprint",
}


class IncompatibleFactorConfiguration(ValueError):
    """An editable payload cannot be migrated without guessing semantics."""


FactorResolver = Callable[[dict[str, Any]], dict[str, Any]]
SourceFingerprintResolver = Callable[[str, str], str]
SourceVersionLoader = Callable[[str, str, str, str], dict[str, Any] | None]
SourceVersionRecorder = Callable[..., dict[str, Any]]


def backfill_current_factor_source_versions(
    *,
    apply: bool = False,
    source_rows: list[dict[str, Any]] | None = None,
    fingerprint_resolver: SourceFingerprintResolver | None = None,
    version_loader: SourceVersionLoader | None = None,
    version_recorder: SourceVersionRecorder | None = None,
) -> dict[str, Any]:
    """Snapshot current family sources under their semantic fingerprints.

    This makes a currently equivalent frozen factor inspectable without ever
    substituting today's source for a genuinely historical fingerprint.
    """
    if source_rows is None:
        from tools.data.sqlite.factor_source_store import list_factor_sources

        source_rows = [
            *list_factor_sources("public"),
            *list_factor_sources("custom"),
        ]
    if fingerprint_resolver is None:
        from server.modules.custom_factors.catalog import (
            _load_factor_family_from_source,
        )

        def fingerprint_resolver(source_code: str, factor_id: str) -> str:
            factor_cls, _ = _load_factor_family_from_source(
                source_code, f"_formula_snapshot_{factor_id}",
            )
            if factor_cls is None:
                raise ValueError("factor family source cannot be loaded")
            return str(factor_cls().expr.semantic_fingerprint())
    if version_loader is None or version_recorder is None:
        from tools.data.sqlite.factor_source_versions import (
            load_factor_formula_version,
            record_factor_formula_version,
        )

        version_loader = version_loader or load_factor_formula_version
        version_recorder = version_recorder or record_factor_formula_version

    planned: list[tuple[str, str, str, str, str]] = []
    errors: list[dict[str, str]] = []
    for row in source_rows:
        kind = str(row.get("source_kind") or "").strip()
        owner = str(row.get("owner_username") or "").strip()
        factor_id = str(row.get("factor_id") or "").strip()
        source_code = str(row.get("source_code") or "")
        try:
            if kind not in {"public", "custom"} or not factor_id or not source_code:
                raise ValueError("factor source identity is incomplete")
            fingerprint = fingerprint_resolver(source_code, factor_id)
            if version_loader(kind, owner, factor_id, fingerprint) is None:
                planned.append((kind, owner, factor_id, source_code, fingerprint))
        except Exception as error:
            errors.append({
                "source_kind": kind,
                "owner_username": owner,
                "factor_id": factor_id,
                "error": str(error),
            })
    migrated = 0
    if apply and not errors:
        for kind, owner, factor_id, source_code, fingerprint in planned:
            version_recorder(
                kind,
                owner,
                factor_id,
                source_code,
                family_formula_fingerprint=fingerprint,
                subject="formula identity migration",
            )
            migrated += 1
    return {
        "eligible": len(source_rows),
        "planned": len(planned),
        "migrated": migrated,
        "errors": errors,
    }


def migrate_editable_configuration_payload(
    payload: Any,
    *,
    resolver: FactorResolver,
    configuration_owner: str = "",
    legacy_alias_family_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Migrate one schema-1 editable payload atomically in memory."""
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
        raise IncompatibleFactorConfiguration(
            "one-time factor migration requires editable configuration schema 1"
        )
    value = deepcopy(payload)
    shared = value.get("shared")
    if not isinstance(shared, dict):
        raise IncompatibleFactorConfiguration("configuration shared section is missing")
    factors = shared.get("factors")
    if not isinstance(factors, list) or not all(isinstance(item, dict) for item in factors):
        raise IncompatibleFactorConfiguration("configuration factors are invalid")

    from tools.factors.factor_param_resolution import factor_param_resolver_scope

    migrated_by_index: dict[int, dict[str, Any]] = {}
    reference_map: dict[str, str] = {}
    runtime_factors: dict[str, Any] = {}
    resolving_dependencies: set[str] = set()
    pending: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for index, factor in enumerate(factors):
        request = _resolver_request(
            factor, index=index, configuration_owner=configuration_owner,
        )
        pending[index] = (factor, request)

    def resolve_nested(value: Any) -> Any:
        if isinstance(value, dict):
            alias = str(value.get("alias") or value.get("factor_alias") or "")
        else:
            alias = str(value or "")
        alias = re.sub(r"\|?\$F:[^|]+", "", alias.strip().strip("[]"))
        if alias not in runtime_factors:
            if alias in resolving_dependencies:
                raise ValueError(f"cyclic factor dependency {alias!r}")
            family_alias = (legacy_alias_family_map or {}).get(
                alias, alias.split("|", 1)[0].strip(),
            )
            if not family_alias:
                raise ValueError(f"factor dependency {alias!r} is invalid")
            resolving_dependencies.add(alias)
            try:
                resolved = resolver({
                    "legacy_ref": "",
                    "owner_ref": "",
                    "family_alias": family_alias,
                    "legacy_alias": alias,
                    "params": {},
                    "configuration_owner": configuration_owner,
                })
                runtime = resolved.get("_runtime_factor")
                if runtime is None:
                    raise ValueError(f"factor dependency {alias!r} has no runtime")
                runtime_factors[alias] = runtime
            finally:
                resolving_dependencies.discard(alias)
        return runtime_factors[alias]

    last_errors: dict[int, Exception] = {}
    with factor_param_resolver_scope(resolve_nested):
        while pending:
            progressed = False
            for index, (factor, request) in list(pending.items()):
                try:
                    resolved = resolver(request)
                    frozen = _validated_resolved_factor(resolved, index=index)
                except Exception as error:
                    last_errors[index] = error
                    continue
                preserved = {
                    key: item for key, item in factor.items()
                    if key not in _IDENTITY_FIELDS and key not in _REMOVED_FACTOR_FIELDS
                }
                migrated_by_index[index] = {**preserved, **frozen}
                old_ref = str(request.get("legacy_ref") or "").strip()
                if old_ref:
                    reference_map[old_ref] = frozen["ref"]
                runtime = resolved.get("_runtime_factor")
                if runtime is not None:
                    for alias in {request["legacy_alias"], frozen["alias"]}:
                        runtime_factors[re.sub(r"\|?\$F:[^|]+", "", alias)] = runtime
                pending.pop(index)
                last_errors.pop(index, None)
                progressed = True
            if not progressed:
                index = min(pending)
                error = last_errors.get(index, ValueError("unresolved factor dependency"))
                raise IncompatibleFactorConfiguration(
                    f"factor {index} cannot be resolved: {error}"
                ) from error

    shared["factors"] = [migrated_by_index[index] for index in range(len(factors))]
    value = _replace_exact_references(value, reference_map)
    value = _remove_legacy_identity_fields(value)
    value["schema_version"] = CONFIGURATION_SCHEMA_VERSION
    _assert_no_removed_factor_identity(value)
    return value


def _remove_legacy_identity_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_legacy_identity_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _remove_legacy_identity_fields(item)
            for key, item in value.items() if key not in _REMOVED_FACTOR_FIELDS
        }
    return value


def migrate_configuration_database(
    database: str | Path,
    *,
    resolver: FactorResolver,
    apply: bool = False,
    discard_incompatible: bool = False,
    control_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    """Explicitly migrate editable workspace/template rows in one transaction."""
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        return {"eligible": 0, "migrated": 0, "errors": []}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='research_configurations'"
        ).fetchone()
        if table is None:
            return {"eligible": 0, "migrated": 0, "errors": []}
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(research_configurations)"
            ).fetchall()
        }
        owner_expression = "owner" if "owner" in columns else "'' AS owner"
        rows = connection.execute(
            f"SELECT configuration_id, payload_json, {owner_expression} "
            "FROM research_configurations WHERE schema_version=1"
        ).fetchall()
        legacy_manifest_rows = connection.execute(
            f"SELECT configuration_id, payload_json, {owner_expression} "
            "FROM research_configurations WHERE schema_version=2 "
            "AND instr(payload_json, 'factor_revision_manifests') > 0"
        ).fetchall()
        legacy_alias_family_map = _legacy_alias_family_map(rows)
        migrated: list[tuple[str, str]] = []
        errors: list[dict[str, str]] = []
        factors_by_legacy_ref: dict[str, dict[str, Any]] = {}
        for row in rows:
            identifier = str(row["configuration_id"])
            try:
                payload = json.loads(str(row["payload_json"] or ""))
                def resolve_and_remember(request: dict[str, Any]) -> dict[str, Any]:
                    resolved = resolver(request)
                    frozen = require_frozen_factor({
                        key: value for key, value in resolved.items()
                        if not str(key).startswith("_")
                    })
                    old_ref = str(request.get("legacy_ref") or "").strip()
                    if old_ref:
                        existing = factors_by_legacy_ref.get(old_ref)
                        if existing is not None and existing != frozen:
                            raise IncompatibleFactorConfiguration(
                                f"legacy factor reference {old_ref!r} resolves inconsistently"
                            )
                        factors_by_legacy_ref[old_ref] = frozen
                    return resolved
                value = migrate_editable_configuration_payload(
                    payload,
                    resolver=resolve_and_remember,
                    configuration_owner=str(row["owner"] or "").strip(),
                    legacy_alias_family_map=legacy_alias_family_map,
                )
            except (ImportError, KeyError, TypeError, ValueError) as error:
                errors.append({"configuration_id": identifier, "error": str(error)})
            else:
                migrated.append((identifier, _canonical_json(value)))
        cleaned_manifests: list[tuple[str, str]] = []
        legacy_manifest_errors: list[dict[str, str]] = []
        for row in legacy_manifest_rows:
            identifier = str(row["configuration_id"])
            try:
                payload = json.loads(str(row["payload_json"] or ""))
                value = _remove_legacy_revision_manifests(payload)
            except (KeyError, TypeError, ValueError) as error:
                legacy_manifest_errors.append({
                    "configuration_id": identifier,
                    "error": str(error),
                })
            else:
                if value is not None:
                    cleaned_manifests.append((identifier, _canonical_json(value)))
        factor_set_plan = _factor_set_migration_plan(
            connection, factors_by_legacy_ref,
        )
        account_domain_plan = _account_domain_migration_plan(
            connection, resolver,
            discard_incompatible=discard_incompatible,
        )
        report = {
            "eligible": len(rows) + len(legacy_manifest_rows),
            "planned": len(migrated) + len(cleaned_manifests),
            "migrated": (
                len(migrated) + len(cleaned_manifests) if apply else 0
            ),
            "errors": [*errors, *legacy_manifest_errors],
            "plan_hash": _plan_hash([*migrated, *cleaned_manifests]),
            "legacy_revision_manifests": {
                "eligible": len(legacy_manifest_rows),
                "planned": len(cleaned_manifests),
                "migrated": len(cleaned_manifests) if apply else 0,
                "errors": legacy_manifest_errors,
            },
            "factor_sets": factor_set_plan["report"],
            "account_domain": account_domain_plan["report"],
        }
        if not apply:
            connection.rollback()
            return report
        if migrated:
            connection.executemany(
                "UPDATE research_configurations "
                "SET schema_version=2, revision=revision+1, payload_json=? "
                "WHERE configuration_id=? AND schema_version=1",
                [(payload, identifier) for identifier, payload in migrated],
            )
        if cleaned_manifests:
            connection.executemany(
                "UPDATE research_configurations "
                "SET revision=revision+1, payload_json=? "
                "WHERE configuration_id=? AND schema_version=2",
                [
                    (payload, identifier)
                    for identifier, payload in cleaned_manifests
                ],
            )
        discarded = _discard_incompatible_configurations(
            connection, errors,
        ) if discard_incompatible else {"templates": 0, "workspaces_reset": 0}
        report["discarded"] = discarded
        _apply_factor_set_migration(connection, factor_set_plan)
        report["factor_sets"]["migrated"] = report["factor_sets"]["planned"]
        _apply_account_domain_migration(connection, account_domain_plan)
        report["account_domain"]["migrated"] = report[
            "account_domain"
        ]["planned"]
        connection.commit()
        if control_plan_path is not None:
            Path(control_plan_path).write_text(
                _canonical_json({"rows": account_domain_plan["rows"]}),
                encoding="utf-8",
            )
        return report
    finally:
        connection.close()


def _remove_legacy_revision_manifests(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 2:
        raise IncompatibleFactorConfiguration(
            "legacy revision manifest cleanup requires configuration schema 2"
        )
    shared = payload.get("shared")
    if not isinstance(shared, dict):
        raise IncompatibleFactorConfiguration("configuration shared section is missing")
    if "factor_revision_manifests" not in shared:
        return None
    factors = shared.get("factors")
    if not isinstance(factors, list):
        raise IncompatibleFactorConfiguration("configuration factors are invalid")
    try:
        for factor in factors:
            require_frozen_factor(factor)
    except (TypeError, ValueError) as error:
        raise IncompatibleFactorConfiguration(
            "legacy revision manifests cannot be removed before factors are frozen"
        ) from error
    value = deepcopy(payload)
    value["shared"].pop("factor_revision_manifests", None)
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )


def _discard_incompatible_configurations(
    connection: sqlite3.Connection, errors: list[dict[str, str]],
) -> dict[str, int]:
    from server.services.research_configurations import empty_payload

    identifiers = [item["configuration_id"] for item in errors]
    templates = 0
    workspaces_reset = 0
    now = time.time()
    for identifier in identifiers:
        row = connection.execute(
            "SELECT * FROM research_configurations "
            "WHERE configuration_id=? AND schema_version=1",
            (identifier,),
        ).fetchone()
        if row is None:
            continue
        connection.execute(
            "DELETE FROM research_configurations WHERE configuration_id=?",
            (identifier,),
        )
        if str(row["role"]) == "template":
            templates += 1
            continue
        connection.execute(
            "INSERT INTO research_configurations ("
            "configuration_id, owner, role, workspace_id, name, schema_version, "
            "revision, payload_json, created_at, updated_at) "
            "VALUES (?, ?, 'workspace', ?, ?, 2, 1, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                row["owner"],
                row["workspace_id"],
                row["name"],
                _canonical_json(empty_payload()),
                now,
                now,
            ),
        )
        workspaces_reset += 1
    return {"templates": templates, "workspaces_reset": workspaces_reset}


def _legacy_alias_family_map(rows: list[sqlite3.Row]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"] or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        factors = (payload.get("shared") or {}).get("factors") or []
        for factor in factors:
            if not isinstance(factor, dict):
                continue
            alias = str(factor.get("factor_alias") or factor.get("alias") or "").strip()
            family = str(
                factor.get("factor_family_alias")
                or factor.get("family_alias") or factor.get("family") or ""
            ).strip()
            if alias and family:
                key = re.sub(r"\|?\$F:[^|]+", "", alias)
                candidates.setdefault(key, set()).add(family)
    return {
        alias: next(iter(families))
        for alias, families in candidates.items() if len(families) == 1
    }


def _factor_set_migration_plan(
    connection: sqlite3.Connection,
    factors_by_legacy_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='account_factor_sets'"
    ).fetchone()
    empty = {
        "required": False,
        "rows": [],
        "report": {"eligible": 0, "planned": 0, "migrated": 0, "errors": []},
    }
    if table is None:
        return empty
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(account_factor_sets)")
    }
    required = not {"owner_ref", "set_id"}.issubset(columns)
    if not required:
        return empty
    source_rows = connection.execute(
        "SELECT username, target_ref, payload_json, updated_at "
        "FROM account_factor_sets"
    ).fetchall()
    migrated: list[tuple[str, str, str, str, str, float]] = []
    errors: list[dict[str, str]] = []
    for row in source_rows:
        old_ref = str(row["target_ref"] or "").strip()
        try:
            payload = json.loads(str(row["payload_json"] or ""))
            username = str(row["username"] or "").strip()
            set_id = str(payload.get("set_id") or "").strip()
            alias = str(
                payload.get("alias") or payload.get("title_zh") or set_id
            ).strip()
            member_refs = payload.get("member_refs")
            if not isinstance(member_refs, list) or not member_refs:
                raise IncompatibleFactorConfiguration(
                    "legacy factor-set has no recoverable members"
                )
            missing = [
                str(ref) for ref in member_refs
                if str(ref) not in factors_by_legacy_ref
            ]
            if missing:
                raise IncompatibleFactorConfiguration(
                    f"factor-set members are unavailable: {missing}"
                )
            value = freeze_factor_set_identity(
                owner_ref=f"principal:{username}",
                set_id=set_id,
                alias=alias,
                members=[factors_by_legacy_ref[str(ref)] for ref in member_refs],
            )
            for key in ("authority", "description", "description_zh", "owner_username"):
                if payload.get(key) not in (None, ""):
                    value[key] = payload[key]
            value["owner_username"] = username
            value["updated_at"] = float(row["updated_at"] or 0)
            frozen = require_frozen_factor_set(value)
            migrated.append((
                username,
                frozen["ref"],
                frozen["owner_ref"],
                frozen["identity"]["set_id"],
                _canonical_json(value),
                float(row["updated_at"] or 0),
            ))
        except (KeyError, TypeError, ValueError) as error:
            errors.append({"target_ref": old_ref, "error": str(error)})
    return {
        "required": True,
        "rows": migrated,
        "report": {
            "eligible": len(source_rows),
            "planned": len(migrated),
            "migrated": 0,
            "errors": errors,
        },
    }


def _apply_factor_set_migration(
    connection: sqlite3.Connection, plan: dict[str, Any],
) -> None:
    if not plan["required"]:
        return
    if plan["report"]["errors"]:
        raise IncompatibleFactorConfiguration(
            "factor-set table migration has unresolved rows"
        )
    connection.execute("DROP TABLE IF EXISTS account_factor_sets_v2_migration")
    connection.execute(
        "CREATE TABLE account_factor_sets_v2_migration ("
        "username TEXT NOT NULL, target_ref TEXT NOT NULL, "
        "owner_ref TEXT NOT NULL, set_id TEXT NOT NULL, "
        "payload_json TEXT NOT NULL, updated_at REAL NOT NULL, "
        "PRIMARY KEY (username, target_ref))"
    )
    connection.executemany(
        "INSERT INTO account_factor_sets_v2_migration "
        "(username, target_ref, owner_ref, set_id, payload_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        plan["rows"],
    )
    connection.execute("DROP TABLE account_factor_sets")
    connection.execute(
        "ALTER TABLE account_factor_sets_v2_migration RENAME TO account_factor_sets"
    )
    connection.execute(
        "CREATE INDEX idx_account_factor_sets_owner_name "
        "ON account_factor_sets (username, owner_ref, set_id, updated_at DESC)"
    )


def _account_domain_migration_plan(
    connection: sqlite3.Connection,
    resolver: FactorResolver,
    *,
    discard_incompatible: bool,
) -> dict[str, Any]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='account_domain_entities'"
    ).fetchone()
    empty = {
        "rows": [],
        "report": {
            "eligible": 0, "planned": 0, "migrated": 0,
            "discarded": 0, "errors": [],
        },
    }
    if table is None:
        return empty
    rows = connection.execute(
        "SELECT principal, entity_type, entity_id, payload_json, deleted, "
        "remote_revision, base_revision FROM account_domain_entities "
        "WHERE deleted=0 AND entity_type IN ('factor_param_config', 'factor_set')"
    ).fetchall()
    planned: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    eligible = 0
    discarded = 0
    for row in rows:
        principal = str(row["principal"] or "").strip()
        entity_type = str(row["entity_type"] or "").strip()
        entity_id = str(row["entity_id"] or "").strip()
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(str(row["payload_json"] or ""))
            if not isinstance(payload, dict):
                raise IncompatibleFactorConfiguration(
                    "account-domain payload is not an object"
                )
            if entity_type == "factor_set":
                try:
                    require_frozen_factor_set(payload)
                    continue
                except (TypeError, ValueError) as error:
                    raise IncompatibleFactorConfiguration(
                        f"legacy synchronized factor set cannot be recovered: {error}"
                    ) from error
            existing = payload.get("resolved_factors")
            if isinstance(existing, list):
                try:
                    for item in existing:
                        require_frozen_factor(item)
                except (TypeError, ValueError):
                    pass
                else:
                    if int(payload.get("schema_version") or 0) != 2:
                        planned.append(_account_domain_change(row, payload, {**payload, "schema_version": 2}, False))
                    continue
            eligible += 1
            params_list = payload.get("params_list")
            if not isinstance(params_list, list):
                raise IncompatibleFactorConfiguration(
                    "factor parameter configuration has no parameter rows"
                )
            family_alias = str(
                payload.get("factor_family_alias") or entity_id.rsplit(":", 1)[-1]
            ).strip()
            if not family_alias:
                raise IncompatibleFactorConfiguration(
                    "factor parameter configuration has no family alias"
                )
            previous = existing if isinstance(existing, list) else []
            frozen_factors = []
            for index, parameter_row in enumerate(params_list):
                if not isinstance(parameter_row, dict):
                    raise IncompatibleFactorConfiguration(
                        f"factor parameter row {index} is invalid"
                    )
                old = previous[index] if index < len(previous) and isinstance(
                    previous[index], dict,
                ) else {}
                source = str(old.get("source") or old.get("factor_kind") or "")
                owner_ref = str(
                    old.get("owner_ref") or old.get("factor_owner_ref") or ""
                ).strip()
                if not owner_ref and source == "public":
                    owner_ref = "public"
                elif not owner_ref and source == "custom":
                    owner_ref = f"principal:{principal}"
                resolved = resolver({
                    "legacy_ref": str(
                        old.get("ref") or old.get("factor_ref") or ""
                    ).strip(),
                    "owner_ref": owner_ref,
                    "family_alias": family_alias,
                    "legacy_alias": str(
                        old.get("alias") or old.get("factor_alias")
                        or family_alias
                    ).strip(),
                    "params": dict(parameter_row),
                    "configuration_owner": principal,
                })
                frozen_factors.append(require_frozen_factor({
                    key: value for key, value in resolved.items()
                    if not str(key).startswith("_")
                }))
            migrated = _remove_legacy_identity_fields(payload)
            migrated["schema_version"] = 2
            migrated["resolved_factors"] = frozen_factors
            metadata = dict(migrated.get("metadata") or {})
            for key in _REMOVED_FACTOR_FIELDS | {"self_formula_fingerprint"}:
                metadata.pop(key, None)
            if frozen_factors:
                metadata["family_formula_fingerprint"] = frozen_factors[0][
                    "identity"
                ]["family_formula_fingerprint"]
            migrated["metadata"] = metadata
            planned.append(_account_domain_change(row, payload, migrated, False))
        except (ImportError, KeyError, TypeError, ValueError) as error:
            errors.append({
                "principal": principal,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "error": str(error),
            })
            if discard_incompatible:
                eligible += entity_type == "factor_set"
                discarded += 1
                tombstone = {
                    "schema_version": 2,
                    "discarded_reason": "incompatible formula identity",
                }
                planned.append(
                    _account_domain_change(row, payload, tombstone, True)
                )
    return {
        "rows": planned,
        "report": {
            "eligible": eligible,
            "planned": len(planned),
            "migrated": 0,
            "discarded": discarded,
            "errors": errors,
        },
    }


def _account_domain_change(
    row: sqlite3.Row,
    old_payload: dict[str, Any],
    new_payload: dict[str, Any],
    new_deleted: bool,
) -> dict[str, Any]:
    revision = int(row["remote_revision"] or 0)
    return {
        "principal": str(row["principal"]),
        "entity_type": str(row["entity_type"]),
        "entity_id": str(row["entity_id"]),
        "expected_revision": revision,
        "old_payload": old_payload,
        "old_deleted": bool(row["deleted"]),
        "new_payload": new_payload,
        "new_deleted": bool(new_deleted),
    }


def _apply_account_domain_migration(
    connection: sqlite3.Connection,
    plan: dict[str, Any],
) -> None:
    for item in plan["rows"]:
        cursor = connection.execute(
            "UPDATE account_domain_entities SET payload_json=?, deleted=?, "
            "remote_revision=?, base_revision=? "
            "WHERE principal=? AND entity_type=? AND entity_id=? "
            "AND coalesce(remote_revision,0)=?",
            (
                _canonical_json(item["new_payload"]),
                int(item["new_deleted"]),
                item["expected_revision"],
                item["expected_revision"],
                item["principal"], item["entity_type"], item["entity_id"],
                item["expected_revision"],
            ),
        )
        if cursor.rowcount != 1:
            raise IncompatibleFactorConfiguration(
                "account-domain mirror changed during formula migration"
            )


def _plan_hash(rows: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for identifier, payload in sorted(rows):
        digest.update(identifier.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def resolve_server_factor(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve one server-owned editable factor through the canonical engine."""
    from server.services.factor_registry import get_factor_family_instance
    from server.services.run_input_inspection import instantiate_factor_metadata
    from tools.data.factor_workspace.storage import (
        load_factor_source,
        load_public_factor_source,
    )

    owner_ref = str(request.get("owner_ref") or "").strip()
    configuration_owner = str(request.get("configuration_owner") or "").strip()
    family_alias = str(request.get("family_alias") or "").strip()
    params = request.get("params")
    if not owner_ref:
        public_exists = load_public_factor_source(family_alias) is not None
        custom_exists = bool(configuration_owner) and (
            load_factor_source(configuration_owner, family_alias) is not None
        )
        if public_exists == custom_exists:
            raise IncompatibleFactorConfiguration(
                f"factor family {family_alias!r} has an ambiguous or missing owner"
            )
        owner_ref = "public" if public_exists else f"principal:{configuration_owner}"
    if owner_ref == "public":
        selector = f"public:{family_alias}"
        username = None
    else:
        username = _server_username(owner_ref)
        selector = f"{username}:{family_alias}"
    family = get_factor_family_instance(selector, username=username)
    family_alias = str(getattr(family, "alias", "") or family_alias).strip()
    if not isinstance(params, dict) or not params:
        legacy_alias = str(request.get("legacy_alias") or "").strip()
        try:
            params = family.parse_alias(legacy_alias)
        except (KeyError, TypeError, ValueError) as error:
            raise IncompatibleFactorConfiguration(
                f"factor parameters cannot be recovered from {legacy_alias!r}: {error}"
            ) from error
    # Account-domain rows are migrated outside the editable-configuration
    # dependency scope. Legacy FactorParam aliases still need the same visible
    # library resolver; otherwise FactorFamily.get_factor() reaches the engine
    # seam without an adapter and aborts the whole release migration.
    from server.modules.shared.factor_param_resolver import (
        resolve_factor_param_value,
    )
    from tools.factors.factor_param_resolution import factor_param_resolver_scope
    with factor_param_resolver_scope(lambda value: resolve_factor_param_value(
        value, username=username,
    )):
        identity = instantiate_factor_metadata(
            family, params, username=username,
        )
    factor = next(
        (
            item for item in reversed(list(getattr(family, "factors", [])))
            if str(getattr(item, "alias", "")) == identity["factor_alias"]
        ),
        None,
    )
    if factor is None:
        raise IncompatibleFactorConfiguration("resolved factor runtime is unavailable")
    frozen = freeze_factor_identity(
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=identity["factor_alias"],
        family_formula_fingerprint=identity["family_formula_fingerprint"],
        self_formula_fingerprint=identity["self_formula_fingerprint"],
        params=identity["normalized_params"],
    )
    return {**frozen, "_runtime_factor": factor}


def _server_username(owner_ref: str) -> str:
    for prefix in ("principal:", "user:"):
        if owner_ref.startswith(prefix):
            username = owner_ref.removeprefix(prefix).strip()
            if username:
                return username
    if owner_ref and ":" not in owner_ref:
        return owner_ref
    raise IncompatibleFactorConfiguration(
        f"server cannot resolve factor owner {owner_ref!r}; migrate it on its client"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(Settings.CACHE_DB_PATH))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--discard-incompatible", action="store_true")
    parser.add_argument("--control-plan")
    arguments = parser.parse_args(argv)
    report = migrate_configuration_database(
        arguments.database,
        resolver=resolve_server_factor,
        apply=arguments.apply,
        discard_incompatible=arguments.discard_incompatible,
        control_plan_path=arguments.control_plan,
    )
    report["source_versions"] = backfill_current_factor_source_versions(
        apply=arguments.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["source_versions"]["errors"]:
        return 1
    if arguments.apply and arguments.discard_incompatible:
        return 0
    return 0 if not report["errors"] else 1


def _resolver_request(
    factor: dict[str, Any], *, index: int, configuration_owner: str = "",
) -> dict[str, Any]:
    family = str(
        factor.get("factor_family_alias")
        or factor.get("family_alias")
        or factor.get("family")
        or ""
    ).strip()
    alias = str(factor.get("factor_alias") or factor.get("alias") or "").strip()
    owner = str(factor.get("factor_owner_ref") or factor.get("owner_ref") or "").strip()
    old_ref = str(factor.get("factor_ref") or factor.get("target_ref") or "").strip()
    params = _parameter_mapping(factor.get("factor_params", factor.get("params")))
    if not family or not alias:
        raise IncompatibleFactorConfiguration(
            f"factor {index} lacks family or alias"
        )
    if not params and _POSITIONAL_ALIAS.search(alias):
        raise IncompatibleFactorConfiguration(
            f"factor {index} has a positional alias without recoverable parameters"
        )
    return {
        "legacy_ref": old_ref,
        "owner_ref": owner,
        "family_alias": family,
        "legacy_alias": alias,
        "params": params,
        "configuration_owner": configuration_owner,
    }


def _parameter_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, list):
        result: dict[str, Any] = {}
        for item in value:
            if not isinstance(item, dict):
                return {}
            key = str(item.get("alias") or item.get("name") or "").strip()
            if not key or key in result:
                return {}
            result[key] = item.get("value")
        return result
    return {}


def _validated_resolved_factor(value: Any, *, index: int) -> dict[str, Any]:
    try:
        clean = {
            key: item for key, item in value.items()
            if not str(key).startswith("_")
        } if isinstance(value, dict) else value
        return require_frozen_factor(clean)
    except (TypeError, ValueError) as error:
        raise IncompatibleFactorConfiguration(
            f"factor {index} resolver omitted formula identity: {error}"
        ) from error


def _replace_exact_references(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_references(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_exact_references(item, mapping)
            for key, item in value.items()
        }
    return value


def _assert_no_removed_factor_identity(value: Any) -> None:
    if isinstance(value, str) and value.startswith(("factor:v1:", "factor-set:v1:")):
        raise IncompatibleFactorConfiguration(
            "configuration still contains an unresolved v1 factor reference"
        )
    if isinstance(value, list):
        for item in value:
            _assert_no_removed_factor_identity(item)
    if isinstance(value, dict):
        forbidden = _REMOVED_FACTOR_FIELDS.intersection(value)
        if forbidden:
            raise IncompatibleFactorConfiguration(
                f"configuration still contains removed factor fields: {sorted(forbidden)}"
            )
        for item in value.values():
            _assert_no_removed_factor_identity(item)


__all__ = [
    "CONFIGURATION_SCHEMA_VERSION",
    "IncompatibleFactorConfiguration",
    "migrate_configuration_database",
    "migrate_editable_configuration_payload",
    "resolve_server_factor",
]


if __name__ == "__main__":
    raise SystemExit(main())
