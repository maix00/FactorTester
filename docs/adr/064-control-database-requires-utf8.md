# ADR 064: PostgreSQL control database requires UTF-8

## Status

Accepted — 2026-08-13

## Context

FactorTester stores usernames, organizations, hierarchy labels, profile metadata,
device names, and client descriptions in the shared PostgreSQL control plane.
The first remote cluster was initialized with `SQL_ASCII`; psycopg consequently
returned text columns as bytes. That broke account matching, super-administrator
authorization, Manager identity projection, and device allow-list enrollment.
It also left non-ASCII organization and device text without database-level
validation.

## Decision

- Every FactorTester control database must use PostgreSQL `UTF8` encoding.
- Bootstrap creates the database with `ENCODING 'UTF8' TEMPLATE template0`, so
  it does not inherit an unsuitable encoding from the cluster's default
  template database.
- Bootstrap rejects an existing control database whose encoding is not UTF-8.
- Runtime connections reject a non-UTF-8 control database before reading or
  writing identity data. Application code must not silently decode arbitrary
  bytes as a substitute for a correctly encoded database.
- Existing `SQL_ASCII` deployments are migrated through a consistent dump into
  a UTF-8 database. The old database and dump are retained until the new
  database has passed account, device, and cross-server authentication checks.

## Consequences

Text values are consistently returned as strings on every Manager, and Chinese
organization, hierarchy, profile, browser, and device labels are validated by
PostgreSQL. A misconfigured database fails with a precise operator error instead
of producing misleading login failures or `b'...'` account identities.
