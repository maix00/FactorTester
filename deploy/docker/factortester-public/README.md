# Public FactorTester containers

This module replaces the native public-host services with exactly two
business containers:

- `factortester-public` owns the FactorTester WireGuard identity and runs
  public Manager `7998`, public data `7997`, and loopback-only main service
  `8000`.
- `postgresql-control` owns a different WireGuard identity and PostgreSQL.

The application and database communicate on the internal `private` Docker
network. Neither `8000` nor TCP `5432` is published. Server peers use
FactorTester's WireGuard-only `17998/17997` listeners when the deployed source
revision contains Issue #184; those ports are never host-published.

## Required host ingress

Production needs TCP `7998`, TCP `7997`, UDP `51820` (FactorTester federation),
and UDP `51821` (database tunnel). Do not open TCP `8000`, TCP `5432`, TCP
`17998`, or TCP `17997` in the public security group. Only authorized server
nodes receive a database-tunnel peer; Swift clients do not.

## Versioned deployment

Copy `public.env.example` outside the repository, replace all example values,
and restrict it and every secret to the owner. `FACTORTESTER_REVISION` must be
the full SHA of a clean checkout. The image embeds that source and disables
hot reload and service debug mode.

Use `scripts/server/factortester_public_container.sh` to validate, build,
start, inspect, back up, restore-check, and verify the deployment. `up` never
builds or pulls implicitly. A PostgreSQL outage does not stop or restart the
FactorTester container; database-backed requests degrade until the independent
database container recovers.

Before replacing a native PostgreSQL instance, create a custom-format dump and
retain a checksum outside the container volume. Restore it into a new named
volume, run `backup` and `restore-check`, then switch the host ports. Keep the
native dump until the container backup has itself passed a restore check.

## Rollback

Stop the two containers without deleting the named volume, restore the prior
native PostgreSQL service if required, and restart the prior Manager unit. The
deployment script's `down` command deliberately omits `--volumes`; it cannot
delete the PostgreSQL volume. Removing native releases, virtual environments,
units, or database files is a separate cleanup step after container validation.
