"""Typed client methods for reusable research Evidence objects."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchEvidenceClientMixin(ClientMixinBase):
    def put_research_evidence(
        self, envelope: dict[str, Any], applicability: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence",
            {"envelope": envelope, "applicability": applicability},
        ))
        return dict(data.get("evidence") or {})

    def get_research_evidence(self, evidence_ref: str) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            f"/api/research-evidence/{evidence_ref}"
        ))
        return dict(data.get("evidence") or {})

    def admit_research_evidence(
        self, evidence_ref: str, *, environment_ref: str,
        subject_ref: str, qualification: str, note: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/{evidence_ref}/admissions",
            {
                "environment_ref": environment_ref,
                "subject_ref": subject_ref,
                "qualification": qualification,
                "note": note,
            },
        ))
        return dict(data.get("admission") or {})

    def admit_research_evidence_for_graph(
        self, evidence_ref: str, *, instance_id: str, branch_id: str,
        qualification: str, note: str = "",
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/{evidence_ref}/graph-admissions",
            {
                "instance_id": instance_id, "branch_id": branch_id,
                "qualification": qualification, "note": note,
            },
        ))
        return dict(data.get("admission") or {})
