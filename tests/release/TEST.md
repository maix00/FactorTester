# Client release pipeline test plan

The publisher and client updater are separate trust boundaries and are tested
without `/Applications`, the live release channel, or real signing keys.

## Publisher

- Runtime input hashing changes for CLI, Harness, adapter, toolchain, or pinned
  runtime inputs, but not for Swift/UI-only changes.
- A matching content-addressed frozen runtime is reused and receives a fresh
  source revision receipt without running PyInstaller.
- The immutable digest-named DMG is materialized before `beta.json`, and the
  manifest is switched by atomic rename.
- `FTClient Beta Release` is the default identity; ad-hoc signing is rejected.
- Publisher code contains no application installation authority.

## Client updater

- The updater has no build, signing, or channel publication authority.
- The signed manifest digest is checked before mounting a DMG.
- Bundle identifier, version, build, code signature, designated requirement,
  bundled runtime files, and receipt are checked before replacement.
- Failed post-install or launch verification restores the prior app.
- Rollback copies and receipts live in Application Support, never Applications.

## Integration

Existing release-builder, update-manifest, server channel, and client command
tests remain the contract suite. A real release is a separate operator action;
tests must use temporary roots and generated test keys only.
