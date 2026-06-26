"""Versioned JSON boundary between GTHT and isolated framework workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    request_id: str
    engine: str
    operation: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported worker schema version: {self.schema_version}")
        if not self.request_id or not self.engine or not self.operation:
            raise ValueError("worker request requires request_id, engine, and operation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "engine": self.engine,
            "operation": self.operation,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkerRequest":
        return cls(
            schema_version=value.get("schema_version", 0),
            request_id=value.get("request_id", ""),
            engine=value.get("engine", ""),
            operation=value.get("operation", ""),
            payload=value.get("payload", {}),
        )


@dataclass(frozen=True, slots=True)
class WorkerResponse:
    request_id: str
    engine: str
    success: bool
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported worker schema version: {self.schema_version}")
        if not self.request_id or not self.engine:
            raise ValueError("worker response requires request_id and engine")
        if self.success == (self.error is not None):
            raise ValueError("worker response must contain either result or error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "engine": self.engine,
            "success": self.success,
            "result": dict(self.result),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkerResponse":
        return cls(
            schema_version=value.get("schema_version", 0),
            request_id=value.get("request_id", ""),
            engine=value.get("engine", ""),
            success=value.get("success", False),
            result=value.get("result", {}),
            error=value.get("error"),
        )
