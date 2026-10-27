# ADR 183: Independent React workspace pages and typed test entry

Status: implementation in progress (issue #445).

## Decision

Desktop navigation creates a fresh DockView panel instance on every click. Page
arguments and draft/navigation state belong to that instance, not a shared URL.
Visible split panels remain active; hidden Job pages close their stream/poll.
Mobile keeps Research, Test, Trading and More as roots; libraries, Jobs and
Settings are nested pages. Account is only inside Settings.

Test kinds come from the authoring schema's analyses registry. Selection changes
the rendered inputs/catalog, not the saved definitions of other analyses.
Submission references the saved workspace revision and selected analysis. Public
and user strategies retain frozen revisions; factor pickers resolve canonical
factor:v2 records using the existing library detail API.

Test results and queue detail use the same JobDetail component. Progress is
reported by the service, never estimated by the browser. Terminal Jobs stop
streaming/polling. Artifact bytes use Manager-issued scoped access grants and the
existing data plane; object URLs are revoked on replacement/unmount.

## Boundaries and remaining acceptance

This does not change execution, factor calculation, Celery or RunSpec compilers.
Local HTTP fixtures verify UI interactions, not real Nautilus execution.

Implemented in the next design pass: native domain library tables/search,
public/user/subordinate strategy scopes, strategy-family view, source-free factor
formula rendering, mobile creator navigation, metadata-driven typed IC inputs,
shared Research lists/detail and Settings presentation cleanup.

Remaining: structured result charts and domain result plugins; complete version
editing/recovery flows; the Research graph editor still uses its existing
embedded route; real authenticated local Job acceptance. Trading has no verified
broker/session management API in this frontend migration: its paper/live entry
must not pretend that broker connections or order execution are available.

No deployment or integration is authorized by this ADR.
