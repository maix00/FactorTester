# Domain Docs Layout

- **Layout**: Single-context
- **CONTEXT.md**: `./CONTEXT.md` (repo root)
- **ADRs**: `./docs/adr/` (repo root)

Consumer rules:
- Skills that read domain context (`improve-codebase-architecture`, `diagnose`, `tdd`) look for a single `CONTEXT.md` at the repo root.
- Architectural Decision Records live under `docs/adr/`.
