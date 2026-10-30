"""Live Keycloak decisions for an already capability-checked 7997 request.

The source does not impersonate an end user or accept a browser-supplied name.
It resolves the stable identity asserted by the signed request-owning Manager
and evaluates the current local Keycloak policies for that exact subject.
Foreign Manager requests additionally require a live delegation verifier.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.identity.keycloak_research import profile_resource_ref
from server.identity.keycloak_research_cutover import KeycloakResearchPolicyEvaluator
from tools.data.sqlite.db import connect_sqlite


class KeycloakResearchTransferAuthorization:
    def __init__(self, catalog, *, evaluator_factory: Callable = KeycloakResearchPolicyEvaluator,
                 verify_foreign_delegation: Callable | None = None) -> None:
        if catalog._profile_authorizer is None:
            raise ValueError("Research Profile policy migration has not been enabled")
        self.catalog = catalog
        self.evaluator_factory = evaluator_factory
        self.verify_foreign_delegation = verify_foreign_delegation

    def authorize(self, *, transfer, record: dict[str, Any], metadata: dict[str, Any]) -> None:
        stable = str(getattr(transfer, "principal_identity_id", "") or "").strip()
        principal = str(getattr(transfer, "principal", "") or "").strip()
        if not stable or not principal:
            raise PermissionError("Research transfer requires a verified stable user identity")
        evaluator = self.evaluator_factory()
        try:
            user = evaluator.adapter.user_by_identity_id(stable)
        except LookupError as exc:
            raise PermissionError("Research transfer Keycloak identity is ambiguous") from exc
        attributes = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(user, dict) or user.get("enabled") is not True or not user.get("id")
                or not isinstance(attributes, dict) or attributes.get("tr_identity_id") != [stable]):
            raise PermissionError("Research transfer Keycloak identity is unavailable")
        legacy = attributes.get("legacy_username")
        if legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1 or not isinstance(legacy[0], str)):
            raise PermissionError("Research transfer principal is ambiguous")
        local_principal = legacy[0] if legacy else str(user.get("username") or "")
        if not local_principal or principal != local_principal:
            raise PermissionError("Research transfer principal does not match its stable identity")
        owner_manager = str(getattr(transfer, "request_owner_manager_id", "") or "")
        source = str(getattr(transfer, "source_server_id", "") or "")
        if not owner_manager or not source:
            raise PermissionError("Research transfer has no authenticated Manager binding")
        if owner_manager != source:
            verifier = self.verify_foreign_delegation
            if verifier is None or verifier(transfer=transfer, identity_id=stable) is not True:
                raise PermissionError("live foreign Manager delegation is required")

        report = self.catalog._publication_report(record)
        if report is None:
            raise PermissionError("Research publication is not registered")
        research = self.catalog._research_row(str(report["research_id"]))
        research_id, report_id = str(research["research_id"]), str(report["report_id"])
        with connect_sqlite(self.catalog.db_path, readonly=True) as db:
            profiles = self.catalog._profile_pairs(db, local_principal, research_id=research_id)
        authoring = metadata.get("purpose") == "report_authoring"
        profile_scopes = ("read", "use", "write") if authoring else ("read", "use")
        candidates = [("research", research_id, ("read", "use", "manage")),
                      ("research_report", report_id, ("read", "use"))]
        candidates.extend(("research_profile", profile_resource_ref(research_id, stable, profile), profile_scopes)
                          for _research, profile in profiles)
        decisions = evaluator.evaluate(stable, candidates=candidates)

        def allowed(kind: str, ref: str, *scopes: str) -> bool:
            return all(decisions.get((kind, ref, scope)) is True for scope in scopes)

        research_visible = (str(research["status"]) == "active"
                            or allowed("research", research_id, "manage"))
        direct_research = research_visible and allowed("research", research_id, "read", "use")
        direct_report = allowed("research_report", report_id, "read", "use")
        with connect_sqlite(self.catalog.db_path, readonly=True) as db:
            current_profiles = self.catalog._profile_pairs(db, local_principal, research_id=research_id)
        # A policy update can happen while Keycloak is answering. Do not use a
        # Profile decision observed against an older local policy revision.
        valid_profiles = [pair[1] for pair, revision in profiles.items() if current_profiles.get(pair) == revision]
        member_read = research_visible and any(
            allowed("research_profile", profile_resource_ref(research_id, stable, profile), "read", "use")
            for profile in valid_profiles
        )
        if not (direct_research or direct_report or member_read):
            raise PermissionError("Keycloak denied Research object download")
        if authoring and not any(
                allowed("research_profile", profile_resource_ref(research_id, stable, profile), "write")
                for profile in valid_profiles):
            raise PermissionError("Keycloak denied Research Profile authoring")
        current_report = self.catalog._publication_report(record)
        current_research = self.catalog._research_row(research_id)
        if (current_report is None or str(current_report["research_id"]) != research_id
                or str(current_research["status"]) != str(research["status"])):
            raise PermissionError("Research publication changed during authorization")
