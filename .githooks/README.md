# Git hooks (offline)

This repo ships optional git hooks that run the test suite before `git commit` / `git push`.

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
- Tests run via `scripts/test.sh` and default to conda env `ft` (override with `FT_ENV_NAME`).
