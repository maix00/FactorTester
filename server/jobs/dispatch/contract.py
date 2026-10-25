"""Versioned broker message for one JobAttempt.

Only identity and frozen RunSpec references cross the broker.  Market data,
DataFrames, factor objects and result artifacts stay in FactorTester storage.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping

SCHEMA_VERSION = 2
_JOB_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DispatchSchemaError(ValueError):
    """A broker message does not match the frozen dispatch contract."""


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DispatchSchemaError(f"{key} must be a non-empty string")
    return value.strip()


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DispatchSchemaError(f"{key} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class DispatchMessage:
    """Broker payload; deliberately small and JSON-only."""

    job_id: str
    attempt: int
    deployment_id: str
    run_spec_hash: str
    job_spec_hash: str
    service_port: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _JOB_ID.fullmatch(self.job_id):
            raise DispatchSchemaError("job_id is not a safe identifier")
        if self.attempt < 1:
            raise DispatchSchemaError("attempt must be >= 1")
        if not self.deployment_id:
            raise DispatchSchemaError("deployment_id is required")
        for name, value in (
            ("run_spec_hash", self.run_spec_hash),
            ("job_spec_hash", self.job_spec_hash),
        ):
            if not _SHA256.fullmatch(value):
                raise DispatchSchemaError(f"{name} must be sha256 hex")
        if isinstance(self.service_port, bool) or not isinstance(self.service_port, int):
            raise DispatchSchemaError("service_port must be an integer")
        if not 1 <= self.service_port <= 65535:
            raise DispatchSchemaError("service_port is out of range")
        if self.schema_version != SCHEMA_VERSION:
            raise DispatchSchemaError(
                f"unsupported dispatch schema: {self.schema_version}"
            )

    @property
    def identity(self) -> tuple[str, int]:
        return self.job_id, self.attempt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "attempt": self.attempt,
            "deployment_id": self.deployment_id,
            "run_spec_hash": self.run_spec_hash,
            "job_spec_hash": self.job_spec_hash,
            "service_port": self.service_port,
        }

    def digest(self) -> str:
        import orjson

        return hashlib.sha256(
            orjson.dumps(self.to_dict(), option=orjson.OPT_SORT_KEYS)
        ).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DispatchMessage":
        version = payload.get("schema_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise DispatchSchemaError("schema_version must be an integer")
        return cls(
            job_id=_required_text(payload, "job_id"),
            attempt=_positive_int(payload, "attempt"),
            deployment_id=_required_text(payload, "deployment_id"),
            run_spec_hash=_required_text(payload, "run_spec_hash"),
            job_spec_hash=_required_text(payload, "job_spec_hash"),
            service_port=_positive_int(payload, "service_port"),
            schema_version=version,
        )


def identity_from_message(payload: Mapping[str, Any]) -> tuple[str, int]:
    """Validate and return (job_id, attempt) without constructing the message."""

    message = DispatchMessage.from_dict(payload)
    return message.identity
