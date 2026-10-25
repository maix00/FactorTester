# ADR 177: Platform i18n with i18next

Status: accepted.

## Decision

All React shell text uses i18next/react-i18next with the `common` namespace in
`web/app/src/i18n.ts`. Keys are shared by desktop and mobile. Language is stored
in `tr.language` and falls back to the browser locale.

- Static labels: keys, not literals.
- Dynamic messages: interpolation/pluralization.
- Numbers/dates/currency: Intl formatting with the selected locale.
- Time zone: independent configuration; changing language never changes it.
- User content (report text, strategy/factor/product names, expressions) stays
  verbatim.
- Backend errors return stable codes/parameters; the UI localizes them.
- Ant Design receives its matching locale; Lightweight Charts gets the same
  locale when mounted.
- Legacy iframe pages keep the same `tr.language` preference during migration.

## Test

`web/app/src/i18n.test.ts` verifies English/Chinese keys, fallback, and that the
shared namespace resolves. Missing keys must fail a future completeness test
rather than silently showing raw keys.
