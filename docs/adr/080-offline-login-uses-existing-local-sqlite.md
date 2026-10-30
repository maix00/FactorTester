# ADR 080: Local SQLite password login

- **Status:** Superseded by [ADR 170](170-keycloak-identity-and-managed-permissions.md)
- **Original date:** 2026-08-14
- **Superseded:** 2026-10-29

This ADR documented a legacy local-password fallback and offline registration
path backed by SQLite `accounts`. It is retained only as decision history.
Do not use its login, registration, migration, or rollback procedures.

Keycloak is the identity and authorization authority. TradeResearch Manager
must fail closed when the configured Keycloak issuer or required authorization
service is unavailable; it must not authenticate against local password
hashes. Realm Groups represent organizations and levels, and Keycloak
Authorization Services enforce scoped administration and object access.

Per-principal research metadata such as product-group definitions is business
data, not identity or permission state. Its one-time migration is handled by
`scripts/import_local_research_metadata_once.py`; it does not import users,
credentials, roles, organization membership, or permissions.
