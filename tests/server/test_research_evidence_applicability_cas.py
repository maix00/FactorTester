from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
import settings as Settings

from server.manager.http import research_object_routes
from server.services.research_evidence_catalog import (
    EvidenceApplicabilityConflict,
    get_composed_evidence,
    list_evidence_page,
    update_evidence_applicability,
)
from server.services.research_evidence_registry import get_evidence
from tests.server.test_research_evidence_listing import _evidence


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "evidence.sqlite"))
    _evidence(0)
    ref = list_evidence_page(owner="alice")["items"][0]["evidence_ref"]
    value = get_evidence(owner="alice", evidence_ref=ref)
    return ref, value["applicability_revision"]


def _scope(group):
    return {"contract_hash": "c" * 64, "methodology_hash": "d" * 64,
            "product_group_refs": [group]}


def test_two_editors_cannot_silently_overwrite_the_same_scope(monkeypatch, tmp_path):
    ref, revision = _setup(monkeypatch, tmp_path)
    barrier = Barrier(2)
    def save(group):
        barrier.wait(timeout=5)
        try:
            return update_evidence_applicability(owner="alice", evidence_ref=ref,
                applicability=_scope(group), expected_applicability_revision=revision)
        except EvidenceApplicabilityConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ["products:first", "products:second"]))
    winners = [value for value in outcomes if value is not None]
    assert len(winners) == 1
    actual = get_composed_evidence(owner="alice", evidence_ref=ref)
    assert actual["applicability"] == winners[0]["applicability"]
    assert actual["applicability_revision"] == winners[0]["applicability_revision"] != revision


def test_patch_requires_revision_and_reports_conflict_with_stable_code(monkeypatch, tmp_path):
    ref, revision = _setup(monkeypatch, tmp_path)
    responses = []
    monkeypatch.setattr(research_object_routes, "json_response",
                        lambda _handler, body, status=200: responses.append((status, body)))
    class Handler(research_object_routes.ResearchObjectRoutesMixin):
        payload = {}
        def _session(self):
            return {"username": "alice"}
        def _json_body(self, _maximum):
            return self.payload
    handler = Handler()
    route = SimpleNamespace(path=f"/api/research-evidence/{ref}/applicability")
    handler.payload = {"applicability": _scope("products:first")}
    assert handler._patch_research_object_routes(route)
    assert responses[-1][0] == 400
    assert responses[-1][1]["code"] == "evidence_applicability_revision_required"
    handler.payload["expected_applicability_revision"] = revision
    assert handler._patch_research_object_routes(route)
    assert responses[-1][0] == 200
    new_revision = responses[-1][1]["evidence"]["applicability_revision"]
    assert new_revision != revision
    handler.payload["applicability"] = _scope("products:second")
    assert handler._patch_research_object_routes(route)
    assert responses[-1][0] == 409
    assert responses[-1][1]["code"] == "evidence_applicability_conflict"
    assert get_evidence(owner="alice", evidence_ref=ref)["applicability_revision"] == new_revision
