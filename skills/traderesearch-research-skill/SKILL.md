---
name: traderesearch-research-skill
description: Use the TradeResearch CLI to conduct reproducible factor research and author independent Research Reports.
---

# TradeResearch research

Use the installed `traderesearch` command. Start with `traderesearch research --help`
and inspect the relevant subcommand before writing. Research, Reports, report
branches, Runs, Jobs, Artifacts, and Evidence are independent objects. A Report
branch is selected by its report workspace ID and branch ID; it is not a
factor-library branch.

Authenticate through the TradeResearch web or desktop client using Keycloak.
The CLI only reuses an already established endpoint-scoped session; it must not
collect local passwords or manage users, organizations, roles, or permissions.

Freeze the data and RunSpec used for every experiment. Check product membership,
date range, availability and protected-sample overlap before treating a result
as validation. Keep source references and artifact hashes with conclusions.

For a report, use `traderesearch research reports --help` to create, edit,
validate, render, fork, compare, copy between branches and publish. Review
each command's preview and validation output before applying changes. Keep the
report owner, Profile, report ID, branch ID and source revision explicit.
Use `traderesearch research evidence --help` for Evidence status and references.

Never infer that an experiment or a report edit succeeded from a prepared
request alone; confirm the persisted Run or report HEAD and its revision.
