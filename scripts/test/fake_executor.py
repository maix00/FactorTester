"""Deterministic executor for dispatch deployment probes only."""

from __future__ import annotations

from server.jobs.dispatch.worker import ExecutionOutcome


class FakeExecutor:
    def execute(self, record, message, context):
        context.report_progress(
            sequence=1, phase="dispatch_probe", completed=1, total=1,
            percent=100.0, message="probe",
        )
        return ExecutionOutcome({"engine": "fake", "port": message.service_port})


executor = FakeExecutor()
