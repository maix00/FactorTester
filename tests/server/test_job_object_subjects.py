from __future__ import annotations

import time

from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.jobs.subjects import (
    factor_formula_subject_ref,
    family_formula_subject_ref,
    job_subjects,
)
from tools.factors.factor_set_identity import build_factor_set_reference
from tools.factors.formula_identity import (
    build_factor_family_reference,
    build_factor_reference,
)

OWNER_REF = "principal:alice"
FAMILY_ALIAS = "Momentum"
FAMILY_FINGERPRINT = "a" * 64
SELF_FINGERPRINT = "b" * 64


def _factor(*, owner_ref: str = OWNER_REF) -> dict[str, object]:
    identity = {
        "owner_ref": owner_ref,
        "family_alias": FAMILY_ALIAS,
        "factor_alias": "Momentum(window=20)",
        "family_formula_fingerprint": FAMILY_FINGERPRINT,
        "self_formula_fingerprint": SELF_FINGERPRINT,
    }
    return {
        "schema_version": 2,
        "ref": build_factor_reference(**identity),
        "alias": identity["factor_alias"],
        "owner_ref": owner_ref,
        "identity": identity,
    }


def _record(job_id: str, job_spec: dict[str, object]) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        run_id=f"run-{job_id}",
        owner="alice",
        workspace_id="workspace-1",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        job_spec=job_spec,
        created_at=time.time(),
    )


def test_job_subjects_deduplicate_and_derive_factor_family() -> None:
    factor = _factor()
    set_ref = build_factor_set_reference(
        owner_ref=OWNER_REF,
        set_id="set-1",
        member_refs=[str(factor["ref"])],
    )

    subjects = job_subjects({
        "factor_candidates": [factor, factor["ref"]],
        "factor_set_refs": [set_ref],
    }, include_formula_subjects=True)

    assert {(item.object_kind, item.object_ref) for item in subjects} == {
        (
            "factor",
            factor["ref"],
        ),
        ("factor", factor_formula_subject_ref(SELF_FINGERPRINT)),
        (
            "family",
            build_factor_family_reference(
                owner_ref=OWNER_REF,
                family_alias=FAMILY_ALIAS,
                family_formula_fingerprint=FAMILY_FINGERPRINT,
            ),
        ),
        ("family", family_formula_subject_ref(FAMILY_FINGERPRINT)),
        ("set", set_ref),
    }
    factor_subject = next(
        item for item in subjects if item.object_ref == factor["ref"]
    )
    family_subject = next(
        item for item in subjects
        if item.object_ref.startswith("factor-family:v2:")
    )
    assert (factor_subject.owner_ref, factor_subject.alias) == (
        OWNER_REF, "Momentum(window=20)",
    )
    assert (family_subject.owner_ref, family_subject.alias) == (
        OWNER_REF, FAMILY_ALIAS,
    )


def test_repository_filters_jobs_by_frozen_factor_objects(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    factor = _factor()
    family_ref = build_factor_family_reference(
        owner_ref=OWNER_REF,
        family_alias=FAMILY_ALIAS,
        family_formula_fingerprint=FAMILY_FINGERPRINT,
    )
    set_ref = build_factor_set_reference(
        owner_ref=OWNER_REF,
        set_id="set-1",
        member_refs=[str(factor["ref"])],
    )
    repository.create(_record("matching", {
        "run_spec": {
            "factor_candidates": [factor],
            "factor_set_refs": [set_ref],
        },
    }))
    repository.create(_record("unrelated", {"run_spec": {"products": ["A"]}}))

    by_factor = repository.list_with_metadata(
        owner="alice", object_kind="factor", object_ref=str(factor["ref"]),
    )
    by_family = repository.list_with_metadata(
        owner="alice", object_kind="family", object_owner_ref=OWNER_REF,
        object_alias=FAMILY_ALIAS,
    )
    by_family_ref = repository.list_with_metadata(
        owner="alice", object_kind="family", object_ref=family_ref,
    )
    by_set = repository.list_with_metadata(
        owner="alice", object_kind="set", object_ref=set_ref,
    )

    assert [item["job"].job_id for item in by_factor] == ["matching"]
    assert [item["job"].job_id for item in by_family] == ["matching"]
    assert [item["job"].job_id for item in by_family_ref] == ["matching"]
    assert [item["job"].job_id for item in by_set] == ["matching"]
    assert repository.count_with_metadata(
        owner="alice", object_kind="factor", object_ref=str(factor["ref"]),
    ) == 1


def test_repository_filters_new_jobs_by_formula_fingerprint_across_owners(
    tmp_path,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    profile_factor = _factor(owner_ref="profile:alice:research")
    repository.create(_record("profile-job", {
        "run_spec": {"factor_candidates": [profile_factor]},
    }))

    by_factor_formula = repository.list_with_metadata(
        owner="alice",
        object_kind="factor",
        object_ref=factor_formula_subject_ref(SELF_FINGERPRINT),
    )
    by_family_formula = repository.list_with_metadata(
        owner="alice",
        object_kind="family",
        object_ref=family_formula_subject_ref(FAMILY_FINGERPRINT),
    )

    assert [item["job"].job_id for item in by_factor_formula] == ["profile-job"]
    assert [item["job"].job_id for item in by_family_formula] == ["profile-job"]


def test_historical_subject_reindex_does_not_add_formula_fingerprints(
) -> None:
    factor = _factor(owner_ref="profile:alice:research")
    subjects = job_subjects({
        "run_spec": {"factor_candidates": [factor]},
    }, include_formula_subjects=False)

    assert factor_formula_subject_ref(SELF_FINGERPRINT) not in {
        item.object_ref for item in subjects
    }
