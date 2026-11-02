"""Recover an editable configuration from a verified, immutable Job.

The Job's workspace can have changed since submission.  Never use it as the
source of a historical configuration: recover only the values frozen in the
Job, and refuse records that cannot be restored faithfully.
"""

from copy import deepcopy

from server.jobs.assurance import canonical_hash
from server.services import execution_plans
from server.services.research_run_identity import hash_run_spec


class HistoricalConfigurationUnavailable(ValueError):
    """The Job lacks a verifiable configuration supported by this editor."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def restore_payload(record, identity, *, owner: str) -> dict:
    """Return a new workspace payload; never alter the Job or its workspace."""
    if identity is None or identity.username != owner or record.owner != owner:
        raise PermissionError("a verified Job owner is required")
    if not record.owner_issuer or not record.owner_subject:
        raise HistoricalConfigurationUnavailable(
            "job_owner_unmigrated", "historical Job owner has not been migrated to Keycloak"
        )
    if (record.owner_issuer, record.owner_subject) != (identity.issuer, identity.subject):
        raise PermissionError("Job owner does not match the verified identity")

    job_spec = record.job_spec
    if not isinstance(job_spec, dict) or not record.job_spec_hash:
        raise HistoricalConfigurationUnavailable("job_spec_unverified", "Job has no verifiable frozen specification")
    if canonical_hash(job_spec) != record.job_spec_hash:
        raise HistoricalConfigurationUnavailable("job_spec_changed", "frozen Job specification has changed")
    run_spec = job_spec.get("run_spec")
    if not isinstance(run_spec, dict) or not record.run_spec_hash:
        raise HistoricalConfigurationUnavailable("runspec_unverified", "Job has no verifiable RunSpec")
    if hash_run_spec(run_spec) != record.run_spec_hash:
        raise HistoricalConfigurationUnavailable("runspec_changed", "frozen RunSpec has changed")

    configuration = run_spec.get("configuration")
    selection = job_spec.get("execution_selection")
    if not isinstance(configuration, dict):
        raise HistoricalConfigurationUnavailable(
            "configuration_missing", "Job has no frozen editor configuration"
        )
    if selection is not None and not isinstance(selection, dict):
        raise HistoricalConfigurationUnavailable(
            "execution_selection_invalid", "frozen execution selection is invalid"
        )
    # Earlier Jobs did not persist a deployment choice.  Preserve the frozen
    # test inputs, but explicitly require a new execution-location resolution.
    if selection is None:
        selection = {"mode": "auto", "manager_id": "", "bundles": []}
    plan = {
        "plan_version": 2,
        "run_spec": {
            "analyses": [record.kind],
            "retention_mode": job_spec.get("retention_mode", record.retention_mode),
            "configuration": deepcopy(configuration),
        },
        "execution": deepcopy(selection),
    }
    try:
        payload = execution_plans.encode(plan)
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalConfigurationUnavailable(
            "configuration_incompatible", "frozen configuration is incompatible with the current editor"
        ) from exc
    # Validation may normalize old configurations; silently discarding an
    # input would make the UI misrepresent the original Job.
    if execution_plans.document(payload) != plan:
        raise HistoricalConfigurationUnavailable(
            "configuration_lossy", "frozen configuration cannot be restored without changing it"
        )
    return payload
