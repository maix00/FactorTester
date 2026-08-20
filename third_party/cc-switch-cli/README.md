# CC Switch CLI attribution

FactorTester invokes the upstream `cc-switch` executable as a private,
loopback-only child process. It does not copy CC Switch request or streaming
conversion logic into FactorTester.

- Project: `SaladDay/cc-switch-cli`
- Upstream: `farion1231/cc-switch`
- Pinned release: `v5.10.2`
- Audited source commit: `bae5cab0be63b951270cfb50bd7e39756c6596d6`
- License: MIT
- Runtime binary: installed by the public FactorTester image build with the
  release archive SHA-256 verified in the Dockerfile

Provider credentials are materialized only in a mode `0600` temporary file
inside a per-Profile `CC_SWITCH_CONFIG_DIR`. The file and directory are removed
when the Profile Agent session stops. The proxy listens only on `127.0.0.1`.
