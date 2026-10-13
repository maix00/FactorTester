# Git hooks (offline)

This repo ships optional git hooks that select affected Python and JS tests before `git commit` / `git push`. Shared or unclassified changes run both complete suites.

Enable:

```bash
git config core.hooksPath .githooks
```

Disable:

```bash
git config --unset core.hooksPath
```

Notes:
- Hooks are **local** to your clone.
- Python tests run via `scripts/test.sh` in conda env `GTHT` (override with `FT_ENV_NAME`). JS tests run via `scripts/test_js.sh` and Node.js.
- The commit hook reads staged changes; the push hook reads outgoing commits. Docs-only changes skip tests; Skill changes retain the bundled activation check.
