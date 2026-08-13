"""RunSpec-ready IC execution bundle with one canonical configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.testers.ic_test.configuration import CompiledICRunConfiguration

from .model import ICJobExecutionPlan
from .planner import plan_ic_jobs


@dataclass(frozen=True, slots=True)
class ICRunExecutionBundle:
    configuration: CompiledICRunConfiguration
    job_plans: tuple[ICJobExecutionPlan, ...]

    @classmethod
    def from_configuration(
        cls, configuration: CompiledICRunConfiguration,
    ) -> ICRunExecutionBundle:
        frozen = CompiledICRunConfiguration.from_dict(configuration.to_dict())
        return cls(frozen, plan_ic_jobs(frozen))

    def to_dict(self) -> dict[str, Any]:
        self._validate()
        return {
            "schema_version": 2,
            "configuration_ref": self.configuration.configuration_ref,
            "configuration": self.configuration.to_dict(),
            "job_plans": [item.to_dict() for item in self.job_plans],
        }

    @classmethod
    def from_dict(cls, value: Any) -> ICRunExecutionBundle:
        if not isinstance(value, dict) or value.get("schema_version") != 2:
            raise ValueError("IC run execution bundle schema_version must be 2")
        configuration = CompiledICRunConfiguration.from_dict(
            value.get("configuration"),
        )
        if str(value.get("configuration_ref") or "") != configuration.configuration_ref:
            raise ValueError("configuration_ref does not match the frozen configuration")
        raw_plans = value.get("job_plans")
        if not isinstance(raw_plans, list):
            raise ValueError("IC run execution bundle job_plans must be a list")
        bundle = cls(
            configuration,
            tuple(ICJobExecutionPlan.from_dict(item) for item in raw_plans),
        )
        bundle._validate()
        return bundle

    def _validate(self) -> None:
        expected_scopes = set(self.configuration.job_partitions)
        actual_scopes = [item.product_scope_ref for item in self.job_plans]
        if set(actual_scopes) != expected_scopes or len(actual_scopes) != len(
            expected_scopes
        ):
            raise ValueError("bundle requires exactly one Job plan per product scope")
        expected = plan_ic_jobs(self.configuration)
        if self.job_plans != expected:
            raise ValueError("bundle Job plans do not match the frozen configuration")


__all__ = ["ICRunExecutionBundle"]
