"""Derive searchable Factor objects referenced by one immutable JobSpec."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tools.factors.formula_identity import build_factor_family_reference


@dataclass(frozen=True, order=True)
class JobSubject:
    object_kind: str
    object_ref: str
    owner_ref: str = ""
    alias: str = ""


def job_subjects(job_spec: object) -> tuple[JobSubject, ...]:
    """Return factor/family/set references without retaining the RunSpec."""
    result: dict[tuple[str, str], JobSubject] = {}
    for value in _objects(job_spec):
        if isinstance(value, str):
            _append_typed(result, value)
            continue
        ref = str(value.get("ref") or value.get("target_ref") or "").strip()
        _append_typed(result, ref)
        identity = value.get("identity")
        if not isinstance(identity, dict):
            continue
        factor_ref = ref if ref.startswith("factor:v2:") else str(
            identity.get("ref") or ""
        ).strip()
        owner_ref = str(
            value.get("owner_ref") or identity.get("owner_ref") or ""
        ).strip()
        factor_alias = str(
            value.get("alias") or identity.get("factor_alias") or ""
        ).strip()
        family_alias = str(identity.get("family_alias") or "").strip()
        fingerprint = str(
            identity.get("family_formula_fingerprint") or ""
        ).strip()
        if factor_ref.startswith("factor:v2:"):
            _put(result, JobSubject(
                "factor", factor_ref, owner_ref, factor_alias,
            ))
        if ref.startswith("factor-family:v2:"):
            _put(result, JobSubject(
                "family", ref, owner_ref, family_alias,
            ))
        if owner_ref and family_alias and fingerprint:
            family_ref = build_factor_family_reference(
                owner_ref=owner_ref,
                family_alias=family_alias,
                family_formula_fingerprint=fingerprint,
            )
            _put(result, JobSubject(
                "family", family_ref, owner_ref, family_alias,
            ))
    return tuple(sorted(result.values()))


def _objects(value: object) -> Iterable[dict[str, Any] | str]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, str):
        yield value


def _put(
    result: dict[tuple[str, str], JobSubject], subject: JobSubject,
) -> None:
    key = (subject.object_kind, subject.object_ref)
    current = result.get(key)
    if current is None or (not current.owner_ref and subject.owner_ref):
        result[key] = subject


def _append_typed(
    result: dict[tuple[str, str], JobSubject], value: str,
) -> None:
    ref = str(value or "").strip()
    for prefix, kind in (
        ("factor-family:v2:", "family"),
        ("factor-set:v2:", "set"),
        ("factor:v2:", "factor"),
    ):
        if ref.startswith(prefix):
            _put(result, JobSubject(kind, ref))
            return


__all__ = ["JobSubject", "job_subjects"]
