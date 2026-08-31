"""Typed client methods for reusable research Evidence objects."""

from __future__ import annotations

from typing import Any

from .client_base import ClientMixinBase


class ResearchEvidenceClientMixin(ClientMixinBase):
    def put_research_evidence_source(
        self, source: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence/sources", source,
        ))
        return dict(data.get("source") or {})

    def capture_job_evidence_source(self, job_id: str) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence/sources/job", {"job_id": job_id},
        ))
        return dict(data.get("source") or {})

    def put_research_evidence_fragment(
        self, source_ref: str, fragment: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/sources/{source_ref}/fragments",
            fragment,
        ))
        return dict(data.get("fragment") or {})

    def list_research_evidence_fragments(
        self, source_ref: str,
    ) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(
            f"/api/research-evidence/sources/{source_ref}/fragments"
        ))
        return list(data.get("fragments") or [])

    def create_fragment_bound_evidence(
        self, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence/compositions", payload,
        ))
        return dict(data.get("evidence") or {})

    def list_research_evidence_facets(self) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            "/api/research-evidence/facets"
        ))
        return dict(data.get("facets") or {})

    def search_research_evidence(
        self, query: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            "/api/research-evidence/search", query=query,
        ))
        return dict(data.get("result") or {})

    def list_research_evidence_catalog(
        self, query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.get(
            "/api/research-evidence/catalog", query=query,
        ))
        return dict(data.get("catalog") or {})

    def prepare_research_evidence_lifecycle(
        self, evidence_ref: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/{evidence_ref}/lifecycle/prepare",
            payload,
        ))
        return dict(data.get("transition") or {})

    def finalize_research_evidence_lifecycle(
        self, transition_ref: str, report_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/lifecycle/{transition_ref}/finalize",
            {"report_receipt": report_receipt},
        ))
        return dict(data.get("lifecycle") or {})

    def list_research_evidence_tags(
        self, *, include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        data = self._expect_success(self.session.get(
            "/api/research-evidence/tags",
            query={"include_retired": "1"} if include_retired else None,
        ))
        return list(data.get("tags") or [])

    def propose_research_evidence_tag(
        self, payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence/tags/proposals", payload,
        ))
        return dict(data.get("proposal") or {})

    def create_research_evidence_tag(
        self, proposal_token: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            "/api/research-evidence/tags",
            {"proposal_token": proposal_token},
        ))
        return dict(data.get("tag") or {})

    def update_research_evidence_tag(
        self, tag_ref: str, *, title_zh: str, description_zh: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.patch(
            f"/api/research-evidence/tags/{tag_ref}",
            {"title_zh": title_zh, "description_zh": description_zh},
        ))
        return dict(data.get("tag") or {})

    def retire_research_evidence_tag(
        self, tag_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/tags/{tag_ref}/retire", {},
        ))
        return dict(data.get("tag") or {})

    def attach_research_evidence_tag(
        self, evidence_ref: str, tag_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.post(
            f"/api/research-evidence/{evidence_ref}/tags",
            {"tag_ref": tag_ref},
        ))
        return dict(data.get("attachment") or {})

    def detach_research_evidence_tag(
        self, evidence_ref: str, tag_ref: str,
    ) -> dict[str, Any]:
        data = self._expect_success(self.session.delete(
            f"/api/research-evidence/{evidence_ref}/tags/{tag_ref}"
        ))
        return dict(data.get("attachment") or {})

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
